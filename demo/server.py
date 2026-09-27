"""Standalone coupon-reservation model for interviews, not production service code."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from time import perf_counter
import json
import os


class CouponDemo:
    def __init__(self, stock=10):
        self.initial_stock = stock
        self.cache_stock = stock
        self.db_stock = stock
        self.issued = set()
        self.pending = set()
        self.counts = {name: 0 for name in ("issued", "sold_out", "duplicate", "rolled_back")}
        self.duration_sum = 0.0
        self.duration_buckets = {bound: 0 for bound in (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1.0)}
        self.lock = Lock()

    def redeem(self, user_id, fail_db=False):
        start = perf_counter()
        try:
            # One lock models an atomic cache reservation plus a conditional DB write.
            # The real system uses different stores; this demo focuses on outcomes.
            with self.lock:
                if user_id in self.issued or user_id in self.pending:
                    outcome = "duplicate"
                elif self.cache_stock == 0:
                    outcome = "sold_out"
                else:
                    self.cache_stock -= 1
                    self.pending.add(user_id)
                    if fail_db or self.db_stock == 0:
                        self.cache_stock += 1
                        self.pending.remove(user_id)
                        outcome = "rolled_back"
                    else:
                        self.db_stock -= 1
                        self.issued.add(user_id)
                        self.pending.remove(user_id)
                        outcome = "issued"
                self.counts[outcome] += 1
                return outcome
        finally:
            elapsed = perf_counter() - start
            with self.lock:
                self.duration_sum += elapsed
                for bound in self.duration_buckets:
                    if elapsed <= bound:
                        self.duration_buckets[bound] += 1

    def state(self):
        with self.lock:
            return {
                "initial_stock": self.initial_stock,
                "cache_stock": self.cache_stock,
                "db_stock": self.db_stock,
                "issued_count": len(self.issued),
                "pending_count": len(self.pending),
                "conservation_gap": self.initial_stock - self.db_stock - len(self.issued),
            }

    def metrics(self):
        state = self.state()
        with self.lock:
            lines = [
                "# HELP coupon_redeem_total Requests by final outcome",
                "# TYPE coupon_redeem_total counter",
            ]
            lines += [f'coupon_redeem_total{{result="{result}"}} {count}' for result, count in self.counts.items()]
            for name in ("cache_stock", "db_stock", "issued_count", "pending_count", "conservation_gap"):
                lines += [f"# TYPE coupon_{name} gauge", f"coupon_{name} {state[name]}"]
            lines += [
                "# HELP coupon_redeem_duration_seconds Request duration",
                "# TYPE coupon_redeem_duration_seconds histogram",
            ]
            lines += [f'coupon_redeem_duration_seconds_bucket{{le="{bound}"}} {count}' for bound, count in self.duration_buckets.items()]
            lines += [
                f'coupon_redeem_duration_seconds_bucket{{le="+Inf"}} {sum(self.counts.values())}',
                f"coupon_redeem_duration_seconds_sum {self.duration_sum}",
                f"coupon_redeem_duration_seconds_count {sum(self.counts.values())}",
            ]
        return "\n".join(lines) + "\n"


demo = CouponDemo(int(os.getenv("DEMO_STOCK", "10")))


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body, content_type="application/json"):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/metrics":
            self.respond(200, demo.metrics(), "text/plain; version=0.0.4")
        elif self.path == "/state":
            self.respond(200, json.dumps(demo.state()))
        elif self.path == "/health":
            self.respond(200, '{"status":"ok"}')
        else:
            self.respond(404, '{"error":"not found"}')

    def do_POST(self):
        if self.path != "/redeem":
            self.respond(404, '{"error":"not found"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("invalid body size")
            request = json.loads(self.rfile.read(length))
            user_id = request["user_id"]
            if not isinstance(user_id, str) or not 0 < len(user_id) <= 64:
                raise ValueError("user_id must be a nonempty string of at most 64 characters")
            if not isinstance(request.get("fail_db", False), bool):
                raise ValueError("fail_db must be boolean")
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self.respond(400, json.dumps({"error": str(exc)}))
            return
        result = demo.redeem(user_id, request.get("fail_db", False))
        self.respond(200 if result == "issued" else 409, json.dumps({"result": result}))


if __name__ == "__main__":
    ThreadingHTTPServer((os.getenv("LISTEN_HOST", "127.0.0.1"), 8080), Handler).serve_forever()
