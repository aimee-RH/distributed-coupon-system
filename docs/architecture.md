# Architecture: Four Workflows and Their Failure Boundaries

The target platform separates merchant configuration, background issuance, interactive redemption, and checkout. Each workflow has a different success definition. A task accepted by the admin API is not a coupon delivered to a user; a Redis reservation is not a database issuance; a discount preview is not a consumed coupon.

## Ownership map

| Module | Entry point in the studied project | Owns | Critical boundary |
| --- | --- | --- | --- |
| Merchant Admin | CouponTemplateController#createCouponTemplate | Template creation and campaign configuration | Duplicate-submit protection, validation, audit log, merchant-scoped persistence |
| Merchant Admin | CouponTaskController#createCouponTask | Recipient file and scheduled distribution task | Stream large Excel inputs; persist the task before dispatch |
| Distribution | CouponTaskSendExecuteConsumer#onMessage and CouponTaskExecuteConsumer#onMessage | Background batch issuance | Resume from progress, control stock, and make retries idempotent |
| Engine | CouponTemplateController#findCouponTemplate | Template lookup | Bloom filter, empty-value cache, and lock address different cache failure modes |
| Engine | UserCouponController#redeemUserCoupon | Interactive redemption | Redis fast rejection followed by durable stock and issuance transaction |
| Engine | CouponTemplateRemindController#createCouponRemind | Reservation reminder scheduling | Delayed delivery, cancellation check, and retry visibility |
| Engine | UserCouponController#createPaymentRecord, #processPayment, #processRefund | Coupon lifecycle around payment | Valid state transitions and repeated callback protection |
| Settlement | CouponQueryController#listQueryCoupons and #listQueryCouponsBySync | Eligibility and discount preview | Correct rules and measured overhead of parallel work |

These entry points are a guide for explaining the private learning project. The runnable code in this repository implements only the redemption row.

## System map

~~~mermaid
flowchart LR
  Merchant --> Admin[Merchant Admin]
  Admin --> MQ[RocketMQ]
  MQ --> Distribution[Distribution workers]
  Customer --> Gateway[Gateway]
  Gateway --> Engine[Coupon Engine]
  Gateway --> Settlement[Settlement]
  Engine --> Redis[(Redis)]
  Distribution --> Redis
  Engine --> MySQL[(MySQL)]
  Distribution --> MySQL
  Settlement --> Redis
  Settlement --> MySQL
~~~

Redis holds hot lookup and reservation state. MySQL holds durable templates, task records, stock, issued coupons, and payment state. RocketMQ separates slow distribution and reminder work from foreground requests. ShardingSphere changes where records live, but does not itself make a hot stock row or cross-shard query cheap.

## Workflow 1: Merchant creates a template or bulk task

A template is validated through a handler chain so rules can be expressed in small, ordered checks. Duplicate-submit protection reduces accidental repeated creation, while a database uniqueness rule is still needed when the business key must be unique. An operation log records who changed campaign settings and when. Merchant-oriented sharding makes merchant administration efficient; it does not automatically optimize user-oriented queries.

For bulk push, stream the Excel file instead of loading every recipient into memory. Parsing and row counting can run outside the HTTP request, but the UI should show task state and distinguish **accepted**, **validated**, **published**, and **issued**. A scheduled task scans for due work and publishes a message. The point at which the task is durably stored matters: an API response must not promise delivery merely because the task row was saved.

## Workflow 2: Distribute to a large audience

~~~mermaid
sequenceDiagram
  participant A as Merchant Admin
  participant Q as RocketMQ
  participant D as Distribution worker
  participant DB as MySQL
  A->>DB: Save task and file reference
  A->>Q: Publish due task
  Q->>D: Deliver task message
  loop Bounded recipient batch
    D->>DB: Check stock and insert issued coupons
    D->>DB: Record progress and failures
  end
  D->>DB: Reconcile committed coupons and task outcome
~~~

The interesting design question is **where to resume** after an interruption. A row checkpoint narrows the replay range, but it cannot prove all earlier writes committed. If the process dies between issuing a coupon and saving progress, replay will revisit that row. The database uniqueness key must make the second attempt harmless. If progress is saved first, the row could be skipped forever. Record failed recipients separately, then reconcile task totals against durable issuance records. A queue redelivery is normal; exactly-once delivery is not the assumption.

A stock row remains a contention point even if user-coupon tables are sharded. A conditional stock update or row lock should be the final stock authority. Retry loops need a bounded strategy and visibility into failure counts rather than hiding repeated conflicts indefinitely.

## Workflow 3: Redeem under contention

The [redemption design](redeem.md) separates three outcomes: confirmed commit, confirmed rollback, and uncertain commit. Redis Lua gives fast atomic pre-reservation across instances. MySQL conditionally decrements stock and inserts a user coupon in one transaction. Token-matched compensation follows only a confirmed rollback. When the outcome is unknown, retry with the same request ID and inspect the durable record before releasing capacity.

The [two-instance experiment](experiment.md) demonstrates this boundary with real Redis and MySQL. It is the executable part of the portfolio.

## Workflow 4: Find, remind, and spend

Template lookup needs three different cache defenses. A Bloom filter rejects definite non-members, an empty-value cache reduces repeated misses for absent IDs, and a lock limits concurrent rebuilds for an existing hot key. A Bloom-positive result is not proof of existence.

Scheduled reminders involve a delayed message, cancellation state, and retry path. A bitmap can compactly represent reservation flags; a cancellation filter can avoid many database reads, but false positives require careful treatment because suppressing a real reminder is a user-visible error. Message consumption should be traceable from schedule through attempted delivery.

Settlement should return both eligible and ineligible coupons with reasons. Redis Pipeline reduces round trips for template reads, but the checkout calculation can still be cheaper synchronously when the per-coupon work is small and thread scheduling overhead dominates. Compare both approaches with the same dataset, warmed caches, completed requests, error rate, and latency distribution. The preview does not consume the coupon: order submission reserves it, payment success consumes it, and cancellation or refund follows an explicit state transition. Repeated payment notifications must not repeat that transition.

## Data placement and interview trade-offs

| Choice | Helps | Does not solve |
| --- | --- | --- |
| Shard templates by merchant | Merchant-scoped management queries | A hot campaign's stock row |
| Shard user coupons by user | Wallet and checkout reads | Cross-user campaign counts without aggregation |
| Pipeline template reads | Network round-trip cost | Incorrect eligibility rules or stale data |
| Redis Lua reservation | Atomic fast-path stock check across instances | Durable issuance or Redis/MySQL atomicity |
| Database uniqueness | Duplicate issuance on replay | Missing progress or reconciliation |
| Distributed lock | Serializing a critical section when justified | Stock correctness without a database constraint |

This is a design analysis, not a claim that every row in the table is implemented by the small lab. The [observability design](observability.md) shows which outcomes should be measured when these workflows run in a full system.
