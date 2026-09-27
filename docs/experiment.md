# Reproducible Failure Experiment

This is the interview path from an architectural claim to evidence. Two separate HTTP processes share a real Redis instance and a real MySQL database. The script checks the API response **and** the state of both stores after each relevant step.

## Setup

~~~sh
docker compose down -v
docker compose up -d --build
python3 demo/verify.py
~~~

The reset command deletes only this Compose project's demo database volume. Run it when you want to reset the deterministic 20-coupon campaign. Instance A is on port 8080, instance B on port 28081.

## What the script proves

| Scenario | Stimulus | Expected result | State evidence |
| --- | --- | --- | --- |
| Confirmed rollback | Alice redeems on A with a before_db fault | rolled_back | Redis stock returns to 20; no database issuance |
| Cross-instance retry | Alice uses a new request ID on B | issued | Both stock values fall to 19; one issued row |
| Uncertain response | Bob redeems on A with an after_commit fault | unknown | Database has committed Bob's coupon |
| Same-request recovery | Bob retries the same request ID on B | replayed | No second issuance or stock decrement |
| Per-user limit | Bob uses another request ID on B | duplicate | Database still has one Bob coupon |
| Shared-stock race | 50 new users alternate across A and B | 18 issued, 32 sold_out | 20 total issued, zero stock, all three reconciliation gaps zero |

The script exits nonzero if any expectation fails. Its final JSON output is an actual result from the local stack, not a performance benchmark. It tests one campaign and one coupon per user. It does not verify cross-region behavior, process-crash recovery, persistence loss, or queue delivery.

## Manual probes

~~~sh
curl -s http://127.0.0.1:8080/state
curl -s http://127.0.0.1:28081/state
curl -s http://127.0.0.1:8080/metrics
~~~

The state endpoint exposes conservation_gap, cache_db_gap, and reservation_gap. Both instances read the same stores, while their request counters are instance-local and must be summed in Prometheus. For a manual single request on a fresh stack:

~~~sh
curl -s -X POST http://127.0.0.1:8080/redeem -H 'Content-Type: application/json' -d '{"user_id":"interview","request_id":"demo-1"}'
~~~

Use a fresh campaign before rerunning the deterministic script after manual requests.
