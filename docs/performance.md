# Performance Evidence: Historical Benchmarks vs Live Demo

This page documents the numbers behind the **Coupon Benchmarks: Historical Evidence** Grafana dashboard. The values come from a local k6 run on 2026-09-16 against the studied project's real Engine, Redis, MySQL, and RocketMQ dependencies. They are summarized independently here; no private source code, raw logs, credentials, or production data are included. Prometheus repeatedly exposes these **fixed observations** so Grafana can render them. A current scrape timestamp does not mean the benchmark ran again. These first-round results predate later code changes and should not be presented as current capacity.

## Test conditions

Mac ARM with 16 GiB RAM and 10 CPUs; Colima limited to 4 CPUs and 4 GiB. Engine ran on Java 17 with a 256–768 MiB heap. The load generator and dependencies shared the same computer. Tests used one hot coupon, warm cache, one redemption per user, and a fixed arrival rate. The gateway and login flow were bypassed. Each k6 iteration sent one HTTP request; success required HTTP 200 and business code 0.

The targets P99 < 200 ms, P99.9 < 500 ms, error rate < 0.1%, acceptance > 99.9%, and zero dropped iterations were exploratory test gates, **not** production SLOs.

## Recorded capacity runs

| Run | Requested rate | Observed HTTP rate | Sent / accepted | HTTP P99 | HTTP P99.9 | Dropped iterations | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| sync-100, 30 s | 100/s | 99.99/s | 3,001 / 3,001 | 188.94 ms | 240.80 ms | 0 | Gates passed; inventory reconciled |
| sync-300, 30 s | 300/s | 127.12/s | 4,007 / 4,007 | 3,062.04 ms | 4,176.80 ms | 4,993 | Gates failed; inventory reconciled |
| sync-100-repeat, 60 s | 100/s | 88.15/s | 5,450 / 5,450 | 3,769.48 ms | 5,410.90 ms | 550 | Gates failed; inventory reconciled |
| mq-100, 30 s | 100/s | 100.02/s | 3,001 / 3,001 | 28.64 ms | 50.80 ms | 0 | HTTP acceptance gates passed; final inventory reconciled |

The MQ P99 and P99.9 measure **HTTP acceptance**, not coupon issuance. Its first post-run audit found 848 issued coupons; a later audit reached 3,001 after about 22.9 seconds of polling. That interval includes query time and is not a per-request completion percentile. The first 100/s sync pass did not repeat under a 60-second run; these observations do not establish sustained 100/s capacity, let alone 10,000 QPS.

Correctness probes deliberately caused rejection: the oversell case sent 501 requests and issued 100 coupons; the one-user duplicate case sent 500 and issued one. Both reconciled stock after settling. Their HTTP request rate is not issuance throughput.

## What the two Grafana dashboards mean

After starting the local Compose stack, open [the historical benchmark dashboard](http://127.0.0.1:3000/d/coupon-benchmark-evidence).

- [Historical benchmark dashboard](../monitoring/benchmark-dashboard.json): fixed measurements from the real project run, including failed rounds and queue backlog evidence. Its metrics use the coupon_benchmark_ prefix and are served on a separate Prometheus scrape job.
- [Live redemption lab dashboard](../monitoring/dashboard.json): current counters, duration histogram, stock, and reconciliation gaps from the independent two-instance Redis/MySQL lab. Its small fixed campaign is not a throughput benchmark.

The historical metrics are stored in [metrics.prom](../benchmarks/metrics.prom). They are a curated summary of the local k6 report, not a live telemetry feed. When a new run is performed, replace the snapshot with its own date and environment notes rather than silently overwriting the meaning of this one.

## Settlement claims need matching evidence

The résumé text mentions Redis Pipeline improving template lookup by more than 2× and synchronous settlement outperforming multithreaded calculation by about 20%. No matching raw JMeter result files were found alongside the current local benchmark report, so those numbers are **not plotted as measured results**. A valid comparison needs the same input coupon counts and discount rules, warmed or cold cache stated explicitly, same machine and load shape, completed requests per second, P95/P99, errors, and identical calculation results. Add those measurements only after a repeatable paired experiment.
