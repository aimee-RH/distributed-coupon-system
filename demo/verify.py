"""Run against a fresh docker compose stack: python3 demo/verify.py."""

from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json


PORTS = (8080, 28081)


def call(port, path, payload=None):
    url = f"http://127.0.0.1:{port}{path}"
    request = Request(url, data=json.dumps(payload).encode() if payload else None,
                      headers={"Content-Type": "application/json"} if payload else {})
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as error:
        return json.load(error)


def check(condition, message):
    if not condition:
        raise AssertionError(message + ". Reset the demo with: docker compose down -v")


def main():
    before = call(8080, "/state")
    check(before["initial_stock"] == 20 and before["issued_count"] == 0, "The database is not fresh")

    failed = call(8080, "/redeem", {"user_id": "alice", "request_id": "alice-first", "fault": "before_db"})
    check(failed["result"] == "rolled_back", "Confirmed rollback did not release the reservation")
    check(call(28081, "/state")["cache_stock"] == 20, "Redis stock leaked after rollback")

    retried = call(28081, "/redeem", {"user_id": "alice", "request_id": "alice-retry"})
    check(retried["result"] == "issued", "The user could not retry on the second instance")

    uncertain = call(8080, "/redeem", {"user_id": "bob", "request_id": "bob-request", "fault": "after_commit"})
    check(uncertain["result"] == "unknown", "The commit-boundary fault was not injected")
    replayed = call(28081, "/redeem", {"user_id": "bob", "request_id": "bob-request"})
    check(replayed["result"] == "replayed", "The second instance did not resolve the same request")
    duplicate = call(28081, "/redeem", {"user_id": "bob", "request_id": "bob-other"})
    check(duplicate["result"] == "duplicate", "A distinct request bypassed the user limit")

    def redeem_one(index):
        port = PORTS[index % 2]
        return call(port, "/redeem", {"user_id": f"load-{index}", "request_id": f"load-request-{index}"})["result"]

    with ThreadPoolExecutor(max_workers=20) as pool:
        outcomes = list(pool.map(redeem_one, range(50)))
    check(outcomes.count("issued") == 18 and outcomes.count("sold_out") == 32,
          "Concurrent requests oversold or failed unexpectedly")

    state = call(8080, "/state")
    check(state["db_stock"] == 0 and state["cache_stock"] == 0 and state["issued_count"] == 20,
          "Final stock or issuance count is wrong")
    check(state["conservation_gap"] == 0 and state["cache_db_gap"] == 0 and state["reservation_gap"] == 0,
          "The stores did not reconcile")
    print(json.dumps({"scenarios": ["rollback and retry", "uncertain commit and replay", "duplicate user",
                                   "two-instance concurrent stock race"], "outcomes": {
                                   "issued": outcomes.count("issued"), "sold_out": outcomes.count("sold_out")},
                      "final_state": state}, indent=2))


if __name__ == "__main__":
    main()
