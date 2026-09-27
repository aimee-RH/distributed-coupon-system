# Redemption: Fast Rejection, Durable Issuance, and Uncertain Outcomes

The interactive path has two responsibilities. Redis rejects impossible requests quickly and reserves capacity atomically; MySQL decides whether a coupon was durably issued. There is no atomic transaction spanning both stores.

## Sequence

~~~mermaid
sequenceDiagram
  participant U as Customer
  participant A as Instance A
  participant R as Redis
  participant DB as MySQL
  participant B as Instance B
  U->>A: Redeem with user and request ID
  A->>R: Lua checks user token and stock
  R-->>A: Reserve one unit
  A->>DB: Conditional stock update and coupon insert
  alt Commit confirmed
    DB-->>A: Committed
    A-->>U: Issued
  else Rollback confirmed
    DB-->>A: Rolled back
    A->>R: Release only the matching token
    A-->>U: Retry is possible
  else Commit outcome uncertain
    DB-->>A: No reliable acknowledgement
    A-->>U: Outcome unknown
    U->>B: Retry with the same request ID
    B->>DB: Look up durable coupon record
    DB-->>B: Existing matching record
    B-->>U: Replayed result
  end
~~~

## The four decisions in code

| Boundary | Decision | Evidence |
| --- | --- | --- |
| Redis Lua | Check the user's token before stock, then decrement and attach the token in one script | [reserve.lua](../demo/reserve.lua) |
| MySQL transaction | Update stock only if stock is positive, then insert the issuance record | [server.py](../demo/server.py), [init.sql](../demo/init.sql) |
| Confirmed failure | Roll back the transaction and release only if the Redis token still belongs to this request | [release.lua](../demo/release.lua) |
| Ambiguous commit | Keep the reservation and return an unknown outcome; a same-ID retry looks up the durable record | [server.py](../demo/server.py), [experiment](experiment.md) |

The database unique keys on campaign and user, plus request ID, are the final duplicate defense. A distributed lock by itself would not enforce those constraints or prevent a stock update from going below zero. The lab models a one-coupon-per-user rule; a multi-coupon limit would require a different key and database constraint.

## Invariants and limits

1. Initial stock equals database stock plus issued count after each committed database transaction.
2. Cache stock equals database stock, and reservation count equals issued count, after all known requests resolve.
3. A repeated request ID cannot issue an extra coupon; a different request ID for the same user cannot bypass the one-coupon rule.

The first invariant is checked against MySQL and should always hold. The Redis comparisons are eventual reconciliation targets. A transient gap can occur between the Lua reservation and database commit; a lasting gap means the reservation needs investigation. This lab does not implement crash recovery, Redis failover, an outbox, or automatic reconciliation. Its fixed-stock, single-campaign setup is meant to make the failure boundary visible, not to stand in for production guarantees.
