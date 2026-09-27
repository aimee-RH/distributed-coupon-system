# High-Concurrency Redemption: Fast Rejection and Final Issuance

## The normal path

```mermaid
sequenceDiagram
  participant U as Customer
  participant E as Redemption service
  participant R as Redis
  participant DB as MySQL
  U->>E: Redeem template T
  E->>R: Lua checks campaign, stock, and user limit; reserves capacity
  alt Redis rejects
    R-->>E: Sold out or limit reached
    E-->>U: Reject quickly
  else Reservation succeeds
    R-->>E: Reservation token
    E->>DB: Transaction: conditional stock update and user coupon insert
    alt Commit confirmed
      DB-->>E: Success
      E-->>U: Coupon issued
    else Rollback confirmed
      DB-->>E: Failure
      E->>R: Release this reservation idempotently by token
      E-->>U: Failed; retry is possible
    end
  end
```

## Why the database checks stock again

Redis filters invalid requests quickly, but its state can lag or diverge from the database after failures. The conditional database update is the durable stock constraint: it decrements stock only while sufficient stock remains. The stock update and user coupon insert belong in one database transaction so that neither can commit alone.

## Three distinct outcomes

| Outcome | Redis reservation | Database write | Next step |
| --- | --- | --- | --- |
| Confirmed success | Retained | Committed | Return success |
| Confirmed rollback | Occupied | Not committed | Release by unique token, idempotently |
| Unknown commit outcome | Occupied | May have committed | Keep evidence, inspect final records, and reconcile |

An exception alone does not prove rollback. For example, a timeout after a successful database commit may look like a failed request to the caller. Releasing stock immediately could allow another coupon to be issued.

## Invariants

- Issued coupons must never exceed initial stock.
- A user's successful redemptions must not exceed the per-user limit.
- Retrying compensation for a confirmed failure must not restore stock twice.
- After reconciliation: initial database stock = issued coupon count + current database stock.

The [standalone demo](../demo/server.py) illustrates these state transitions. A process-local lock models atomic reservation; it deliberately does not model distributed transactions, process crashes, duplicate MQ delivery, or Redis failover. Those require separate integration tests against the real system.
