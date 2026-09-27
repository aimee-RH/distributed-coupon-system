# Observability: Show Customer Outcomes and Inventory Truth

Fast HTTP responses are not proof of issued coupons. The dashboard therefore puts request outcomes beside database stock, Redis stock, issuance count, and reconciliation gaps. Prometheus scrapes both redemption instances every five seconds; Grafana provisions the dashboard automatically.

## Read the dashboard from left to right

| Panel / signal | Query or metric | Interpretation |
| --- | --- | --- |
| Request outcomes | Sum the redemption counter by result across both instances | Separate issued, replayed, duplicate, sold-out, confirmed rollback, and unknown outcomes |
| Stock and issued coupons | Database stock, cache stock, and issued count | Compare durable and fast-path views rather than relying on one store |
| Conservation gap | Initial stock minus database stock minus issued count | A nonzero value contradicts the durable inventory ledger |
| Reservation gap | Reservation count minus issued count | A lasting positive value suggests an uncompleted or unreconciled reservation |
| Cache minus DB stock | Cache stock minus database stock | Shows Redis/MySQL divergence, including one that a request counter misses |
| P95 / P99 | Redemption duration histogram | Synchronous endpoint latency, not asynchronous delivery latency |
| Per-instance requests and scrape health | Instance-level counters and Prometheus up | Reveal an unavailable node or traffic concentrated on one node |

The alerts fire on a sustained nonzero conservation gap, a positive reservation gap, or an unavailable instance. A transient reservation gap during a healthy in-flight request is expected, so the reservation alert waits five minutes. An alert cannot fix a mismatch; the next operational step is to inspect the request ID and durable issuance record before changing Redis stock.

## Demonstration script

Run the [verification script](../demo/verify.py) on a fresh stack, then inspect the dashboard. The counter for rolled_back rises once, followed by successful issuance on the other instance. The unknown counter rises after an injected post-commit response fault, then replayed rises when that same request reaches the other instance. The concurrent phase consumes the remaining stock without a conservation gap. [The experiment guide](experiment.md) records the expected results.

The fault named after_commit deliberately returns an uncertain response **after** a successful commit. It demonstrates why the caller cannot infer failure from a 503, but it does not reproduce a real network partition or server crash. The before_db fault demonstrates a confirmed rollback and token-matched compensation.

## Extending the target system

For bulk distribution, record input rows accepted, messages published, rows attempted, coupons committed, failed rows, and oldest pending task age separately. A row checkpoint is not a delivery counter. For reminders, record scheduled, consumed, suppressed, retried, and delivered outcomes. Across modules, propagate a business request ID in logs and traces; keep user IDs, request IDs, and campaign IDs **out of Prometheus labels** to avoid unbounded cardinality.

This lab uses a small SCAN-based reservation count, appropriate only for a tiny demo. A production reconciliation job should compute scoped counts from durable records and bounded Redis evidence without scanning an entire hot keyspace on each scrape. The [dashboard](../monitoring/dashboard.json) and [alert rules](../monitoring/alerts.yml) are reviewable source files.
