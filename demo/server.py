"""Independent Redis + MySQL redemption lab; intentionally not production code."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from time import perf_counter
import json
import os
import re

import pymysql
import redis


CAMPAIGN_ID = 1
STOCK_KEY = "demo:coupon:1:stock"
USER_KEY = "demo:coupon:1:user:"
RESERVE = Path(__file__).with_name("reserve.lua").read_text()
RELEASE = Path(__file__).with_name("release.lua").read_text()
VALID_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class InjectedFailure(Exception):
    pass


class NoDatabaseStock(Exception):
    pass


class Metrics:
    results = ("issued", "replayed", "sold_out", "duplicate", "pending", "rolled_back", "unknown", "error")
    bounds = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1.0)

    def __init__(self):
        self.lock = Lock()
        self.counts = dict.fromkeys(self.results, 0)
        self.buckets = dict.fromkeys(self.bounds, 0)
        self.duration_sum = 0.0

    def record(self, result, elapsed):
        with self.lock:
            self.counts[result] += 1
            self.duration_sum += elapsed
            for bound in self.bounds:
                if elapsed <= bound:
                    self.buckets[bound] += 1

    def render(self, state):
        with self.lock:
            lines = ["# HELP coupon_redeem_total Redemption requests by outcome", "# TYPE coupon_redeem_total counter"]
            lines += [f'coupon_redeem_total{{result="{name}"}} {count}' for name, count in self.counts.items()]
            for name in ("cache_stock", "db_stock", "issued_count", "reservation_count",
                         "conservation_gap", "cache_db_gap", "reservation_gap"):
                lines += [f"# TYPE coupon_{name} gauge", f"coupon_{name} {state[name]}"]
            lines += ["# HELP coupon_redeem_duration_seconds Request duration",
                      "# TYPE coupon_redeem_duration_seconds histogram"]
            lines += [f'coupon_redeem_duration_seconds_bucket{{le="{bound}"}} {count}'
                      for bound, count in self.buckets.items()]
            total = sum(self.counts.values())
            lines += [f'coupon_redeem_duration_seconds_bucket{{le="+Inf"}} {total}',
                      f"coupon_redeem_duration_seconds_sum {self.duration_sum}",
                      f"coupon_redeem_duration_seconds_count {total}"]
        return "\n".join(lines) + "\n"


class CouponService:
    def __init__(self):
        self.redis = redis.Redis(host=os.getenv("REDIS_HOST", "redis"), decode_responses=True,
                                 socket_connect_timeout=2, socket_timeout=2)
        self.mysql_options = dict(host=os.getenv("MYSQL_HOST", "mysql"), user="coupon",
                                  password=os.getenv("MYSQL_PASSWORD", "coupon-demo"),
                                  database="coupon_demo", connect_timeout=3, autocommit=False)
        self.metrics = Metrics()
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT stock FROM campaign WHERE id = %s", (CAMPAIGN_ID,))
                stock = cursor.fetchone()[0]
        self.redis.setnx(STOCK_KEY, stock)

    def connect(self):
        return pymysql.connect(**self.mysql_options)

    def redeem(self, user_id, request_id, fault=None):
        started = perf_counter()
        try:
            result = self._redeem(user_id, request_id, fault)
        except Exception:
            result = "error"
        self.metrics.record(result, perf_counter() - started)
        return result

    def _redeem(self, user_id, request_id, fault):
        user_key = USER_KEY + user_id
        reservation = self.redis.eval(RESERVE, 2, STOCK_KEY, user_key, request_id)
        if reservation == 1:
            return "sold_out"
        if reservation in (2, 3):
            with self.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT request_id FROM issued_coupon WHERE campaign_id = %s AND user_id = %s",
                                   (CAMPAIGN_ID, user_id))
                    row = cursor.fetchone()
            if row and row[0] == request_id:
                return "replayed"
            if row:
                return "duplicate"
            return "pending" if reservation == 3 else "duplicate"
        if reservation != 0:
            return "error"

        connection = None
        commit_started = False
        try:
            connection = self.connect()
            connection.begin()
            if fault == "before_db":
                raise InjectedFailure()
            with connection.cursor() as cursor:
                cursor.execute("UPDATE campaign SET stock = stock - 1 WHERE id = %s AND stock > 0",
                               (CAMPAIGN_ID,))
                if cursor.rowcount != 1:
                    raise NoDatabaseStock()
                cursor.execute("INSERT INTO issued_coupon (campaign_id, user_id, request_id) VALUES (%s, %s, %s)",
                               (CAMPAIGN_ID, user_id, request_id))
            commit_started = True
            connection.commit()
            # The client sees an uncertain response although the commit completed.
            return "unknown" if fault == "after_commit" else "issued"
        except Exception as exc:
            if commit_started:
                return "unknown"
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    return "unknown"
            try:
                released = self.redis.eval(RELEASE, 2, STOCK_KEY, user_key, request_id)
            except Exception:
                return "unknown"
            if released != 1:
                return "unknown"
            if isinstance(exc, NoDatabaseStock):
                return "sold_out"
            if isinstance(exc, pymysql.IntegrityError):
                return "duplicate"
            return "rolled_back" if isinstance(exc, InjectedFailure) else "error"
        finally:
            if connection is not None:
                connection.close()

    def state(self):
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT initial_stock, stock FROM campaign WHERE id = %s", (CAMPAIGN_ID,))
                initial_stock, db_stock = cursor.fetchone()
                cursor.execute("SELECT COUNT(*) FROM issued_coupon WHERE campaign_id = %s", (CAMPAIGN_ID,))
                issued_count = cursor.fetchone()[0]
        cache_stock = self.redis.get(STOCK_KEY)
        reservation_count = sum(1 for _ in self.redis.scan_iter(match=USER_KEY + "*"))
        cache_stock = int(cache_stock) if cache_stock is not None else float("nan")
        return dict(initial_stock=initial_stock, db_stock=db_stock, cache_stock=cache_stock,
                    issued_count=issued_count, reservation_count=reservation_count,
                    conservation_gap=initial_stock - db_stock - issued_count,
                    cache_db_gap=cache_stock - db_stock,
                    reservation_gap=reservation_count - issued_count)


service = CouponService()


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body, content_type="application/json"):
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        try:
            if self.path == "/metrics":
                self.respond(200, service.metrics.render(service.state()), "text/plain; version=0.0.4")
            elif self.path == "/state":
                self.respond(200, json.dumps(service.state()))
            elif self.path == "/health":
                self.respond(200, '{"status":"ok"}')
            else:
                self.respond(404, '{"error":"not found"}')
        except Exception:
            self.respond(503, '{"error":"dependency unavailable"}')

    def do_POST(self):
        if self.path != "/redeem":
            self.respond(404, '{"error":"not found"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("invalid body size")
            request = json.loads(self.rfile.read(length))
            user_id, request_id = request["user_id"], request["request_id"]
            fault = request.get("fault")
            if not isinstance(user_id, str) or not VALID_ID.fullmatch(user_id):
                raise ValueError("invalid user_id")
            if not isinstance(request_id, str) or not VALID_ID.fullmatch(request_id):
                raise ValueError("invalid request_id")
            if fault not in (None, "before_db", "after_commit"):
                raise ValueError("invalid fault")
        except (ValueError, KeyError, TypeError) as exc:
            self.respond(400, json.dumps({"error": str(exc)}))
            return
        result = service.redeem(user_id, request_id, fault)
        status = 200 if result in ("issued", "replayed") else 202 if result == "pending" else 503 if result in ("unknown", "error") else 409
        self.respond(status, json.dumps({"result": result, "request_id": request_id}))


if __name__ == "__main__":
    ThreadingHTTPServer((os.getenv("LISTEN_HOST", "0.0.0.0"), 8080), Handler).serve_forever()
