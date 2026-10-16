# Controlled observations (Steps 12–14)

These optional experiments reuse the accepted schema, fixtures and deployed SQL.
The host creates fresh clones of the sealed template; scoped workers collect facts.
Analysis uses saved receipts after ownership-checked cleanup. Existing configurations
retain their SQL/application flow. No new dependency is needed.

## Controlled contention

Run `pg-rehearse run --config examples/orders/contention.yml` (expected 0), or
`contention-timeout.yml` (expected 4). Each uses an ordinary index migration.

```yaml
contention:
  blocker:
    id: hold-order-write
    sql: UPDATE orders SET amount_cents=amount_cents WHERE id=%s;
    parameters: [101]
    expect: {row_count: 1}
  probe:
    id: queued-writer
    sql: UPDATE orders SET amount_cents=amount_cents WHERE id=%s;
    parameters: [102]
    expect: {row_count: 1}
  poll_ms: 50
  observe_ms: 400
  release: after_observation
```

The blocker completes an UPDATE inside a deliberately open transaction. Its outer
transaction remains open while the migrator starts. A separate read-only observer
samples `pg_stat_activity`, `pg_locks` and `pg_blocking_pids()`, filtered to the four
known backend PIDs; it does not read application rows or retain query text. Only an
observed migration wait starts the declared application probe. The blocker releases
after the probe completes or its wait behind the migrator is observed. There is a
bounded observation fallback. The outer transaction rolls back on every exit;
actor connections and the owned worker are then disposed.

`release: migration_timeout` deliberately holds the blocker until the migration
finishes or its server deadline expires. Its SQLSTATE 55P03 and unsuccessful
migration remain inconclusive evidence, even though the wait was intentionally
induced. A wait alone is informational; it does not fail the passing release case.
The probe runs rollback-only. Its failure remains visible, rather than being hidden
by releasing the blocker afterward.

`poll_ms` is 10–1000, `observe_ms` is 50–10000, and preflight requires
`poll_ms <= observe_ms < timeouts.lock_ms`. At most 1000 samples are retained.
Samples contain UTC timestamps, local monotonic offsets, observer query overhead,
missed polls, activity state/wait event, lock mode/type/grant/wait-start and blocker
PIDs. Client barriers and actual hold duration are retained too. Sample intervals
estimate observed spans, not exact continuous waits or predicted production outages.
An observed snapshot without a wait differs from an unavailable observer. Both
remain inconclusive when this scenario requires a migration wait. An UPDATE on an
unrelated table, or CHECK validation that does not conflict with an ordinary writer,
therefore cannot silently pass this expected-wait scenario.

The main worker and host enforce the overall deadline; SQL actor threads retain
server statement/lock timeouts. There is no production traffic capture, lock-free
certificate, logging dependency or generic concurrency scheduler.

## Advisory performance

Run `pg-rehearse run --config examples/orders/benchmark.yml` (compatibility exit 0).
This is an opt-in small-fixture measurement example, not a latency improvement claim.

```yaml
benchmark:
  operations: [list-orders]
  trials: 5
  warmups: 50
  samples: 200
  absolute_ms: 5.0
  ratio: 1.20
timeouts:
  worker_seconds: 900
```

IDs select existing deployed contract SQL, parameters and semantic assertions.
Candidate application rewrites are not substituted. Each selected operation is one
parameter bucket. There are at most five buckets, five trials, 100 warmups and 1000
measured attempts per bucket/arm. Operations run in declaration order for each
iteration, on one connection with concurrency 1 and prepare_threshold 0. Warmups
are retained separately and excluded from measured percentiles. Client timings
include the existing harness validation/assertions, binding, complete bounded result
consumption and transaction commit; they are not PostgreSQL execution-only times.

Each trial uses four fresh, verified branches: baseline, migrated candidate and two
unchanged-schema A/A controls. Odd trials run control A/B then baseline/candidate;
even trials reverse that order. Arms never run concurrently. All arms ANALYZE after
schema preparation. Writes commit; warmup writes have the same schedule in every
arm. Finished benchmark databases are released by fixed host SQL only after their
exact run/owner/template/branch marker and administrator owner match. This prevents
twenty database copies accumulating in the bounded tmpfs. Workers have no database
administration permission. The receipts retain the initial fixture digest for every
branch. Other clones and Docker resources keep the existing final cleanup flow.

Schedules are fixed and hashed. Choose repeatable operations, such as reads or
updates, with assertions appropriate to the changing state. A repeated INSERT of
the same primary key will report duplicate errors; the tool does not invent new
parameters, roll back writes to hide state or replace failed samples. Timeouts keep
their deadline-sized observed duration and are counted separately from successful
latency. Raw attempted timings, counts, warmups, errors, timeouts, median, p95,
median absolute deviation, extrema and successful throughput over attempted client
time are retained. No p99 or confidence interval is claimed.

The versioned advisory heuristic needs five pairs, at least 200 successful measured
samples per bucket/arm/trial, at least one successful warmup per bucket and unchanged controls. It requires
a median p95 increase of both 5 ms and 20%, with both thresholds in four of five
pairs. Thresholds are configurable. Zero baselines and missing/error samples are
insufficient; controls crossing the thresholds in either direction, or excessive
between-trial spread, are noisy. Findings are warnings. Status is explicitly
`insufficient`, `noisy`, `regression_warning` or `no_regression_observed`.
Performance is optional/advisory: insufficient timing evidence does not invalidate
complete compatibility evidence. No strict performance gate or improvement badge
exists. A worker/runtime failure still retains the normal infrastructure outcome.

Reports record image content IDs/digest, architecture, configured Docker CPU/memory/storage,
seed, PostgreSQL settings, timer resolution, preparation and connection policy.
Synthetic data, a shared runner, closed-loop scheduling and harness overhead limit
interpretation. This does not measure arrival-rate queue growth or production capacity.

## Query plans

Run `pg-rehearse run --config examples/orders/plans.yml` (expected 0). The fixed
fixture has 6002 orders: user 7 owns one, user 8 owns 6001. It demonstrates an index
plan change without disabling sequential scans or changing cost settings.

```yaml
plans:
  operations: [list-orders]
  analyze: true
```

`analyze` defaults to false: plain `EXPLAIN (FORMAT JSON)` does not execute the
statement. Explicit true runs `EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, FORMAT JSON)`.
Preflight has already restricted the selected SQL. Both arms use their own fresh
clones and unprepared diagnostic connections, separately from timed samples and
compatibility probes. Execution-capable write plans commit on their disposable
plan branch and record commit completion; these effects cannot reach benchmark,
compatibility or rollback branches. Rollback is not used as a claim that every
possible side effect is reversible.

Private `plan_baseline-evidence.json` and `plan_candidate-evidence.json` receipts
retain the original plan, including unknown fields, with mode 0600. Raw predicates
may contain fixture/parameter literals; shared JSON/Markdown summaries reference
these files and omit the raw tree. Version-1 normalization retains node/join types,
relation/index identity, child order, scan direction, plan options and parsed
expression shapes with constants removed. Metrics retain estimates, actual rows and
loops, costs, buffer counts, spills and planning/execution time separately. Volatile
metrics do not enter the structural hash. Plans are limited to 256 KiB each, 2000
nodes and depth 64; five operations per arm. Missing/failed/malformed plans are
explicitly unavailable and cannot claim a structural match or change. Root structure
replacement is reported rather than aligning unrelated nodes.

Plan changes are informational. A sequential scan can be correct for small tables;
index scans are not automatic improvements and planner costs are not milliseconds.
Literal diagnostics on fresh connections can differ from a production pooled generic
plan. Neither plan differences nor advisory timing warnings fail compatibility.

## Reference

The implementation follows blueprint pages 21–25 and the PostgreSQL 17 references:
[explicit locks](https://www.postgresql.org/docs/17/explicit-locking.html),
[activity/statistics](https://www.postgresql.org/docs/17/monitoring-stats.html),
[using EXPLAIN](https://www.postgresql.org/docs/17/using-explain.html) and
[EXPLAIN execution behavior](https://www.postgresql.org/docs/17/sql-explain.html).
