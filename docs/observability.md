# Observability and Failure Demo

Monitoring should answer three questions: Did the request succeed? Has the coupon actually been issued? Does the inventory ledger still balance? HTTP latency alone cannot answer the last two.

## From requests to business outcomes

| Signal | Metric | What it tells us |
| --- | --- | --- |
| Redemption outcome | `coupon_redeem_total{result=...}` | Separate successful issuance, sold-out responses, duplicates, and confirmed rollbacks |
| Request duration | `coupon_redeem_duration_seconds` | P95/P99 of the synchronous demo path |
| Database stock | `coupon_db_stock` | Durable remaining inventory in the model |
| Cache stock | `coupon_cache_stock` | Potential divergence from database inventory |
| Issued count | `coupon_issued_count` | Coupons actually issued in the model |
| Conservation gap | `coupon_conservation_gap` | `initial stock - database stock - issued count`; expected value: 0 |
| Pending reservations | `coupon_pending_count` | Reservations left unresolved for too long |

The demo uses only low-cardinality labels such as `result`. In a real service, user IDs, order IDs, and template IDs belong in logs or trace context rather than Prometheus labels.

## Live interview walkthrough

1. Run `docker compose up` and open the **Coupon Reservation Demo** dashboard in Grafana.
2. Send a request for `alice` with `fail_db=true`. The `rolled_back` count should rise, neither stock value should decrease, and the conservation gap should remain zero.
3. Retry for the same user. The `issued` count should rise, and both stock values should decrease by one.
4. Send the same request again. The `duplicate` count should rise without another stock decrement.
5. Explain how the real system would correlate a trace ID across HTTP, Redis Lua, the database transaction, and MQ consumption.

This walkthrough tests **failure-state transitions and visibility**. Two in-memory values stand in for the stores, so it is not a throughput benchmark or a distributed failure test. The inventory-gap alert becomes useful when a real reconciliation job supplies the metric.

## Connecting a real system

- Propagate one business request ID through the redemption endpoint, transaction completion callback, and MQ consumer.
- Measure request acceptance time separately from user coupon commit time; a quick asynchronous response does not prove quick delivery.
- Track queued tasks, age of the oldest unconsumed message, failed messages, and duration per distribution batch.
- Run periodic reconciliation between database stock and issued coupons, with an explicit campaign scope and observation time.
- Alert first on customer impact and correctness: sustained inventory gaps, growing backlog, or a drop in successful issuance. Normal sold-out responses need no alert.

The demo dashboard and alert definitions are under [`monitoring/`](../monitoring/). Prometheus scrapes the service's text-format metrics, and Grafana loads the data source and dashboard at startup.
