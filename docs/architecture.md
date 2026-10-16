# Architecture

## Product goal

Check whether a PostgreSQL migration preserves the behavior required by deployed
and candidate application versions, including rollout phases. A successful DDL
statement alone does not establish compatibility.

## Current implementation

The CLI checks its environment, loads configuration/contracts, and runs a disposable
PostgreSQL lifecycle using `sandbox`. The runtime records allocation intents before
creating resources, saves returned IDs atomically, verifies TCP readiness, and
cleans up using matched ownership labels. `recover` can finish an inactive run.
`run` uses scoped workers to seed a verified template and execute fresh baseline,
deployed and candidate branches. It commits migrations before application probes,
then derives compatibility findings and coverage from recorded evidence. Final
terminal/JSON/Markdown/HTML reports follow cleanup. Preflight and copied snapshots gate
allocation and are rechecked inside workers. See [worker.md](worker.md),
[baseline.md](baseline.md) and [rehearsal.md](rehearsal.md).

## Target run lifecycle

```text
CLI -> validate inputs -> host coordinator -> owned Docker runtime
                                            |
                                  isolated database worker
                                            |
                  seed -> seal -> clone baseline/deployed/candidate -> probes
                                            |
                         recorded evidence -> cleanup -> analysis -> reports
                                            |
                       final completion / verdict / coverage / cleanup
```

The coordinator alone has access to the Docker socket. Each run has a unique ID,
private network, ownership labels, and durable resource manifest. Cleanup checks
both manifest IDs and labels; it never prunes unrelated Docker resources.

The worker receives only resolved inputs and scoped database credentials, with no
Docker socket. Split setup, migration, workload, and observation privileges.
Apply statement and lock deadlines. Dispose of resources on success, failures,
interruptions, and readiness timeouts. Treat a cleanup failure as visible evidence.

Run baseline checks before applying a migration. A broken baseline is a setup
failure, not proof of migration incompatibility. Commit migration steps according
to their declared transaction mode. Reset failed transactions before continuing.

For independent experiments, clone immutable, verified templates. Steps 9–11 add
explicit schema-first phases, persistent/fresh sessions, committed mixed writes,
a separate application rollback branch and maintained HTTP reference probes.
See [rollout.md](rollout.md) for the implemented input/evidence envelope. Rollout
experiments deliberately preserve sessions and committed mixed-version writes.
Rollback experiments run separately. Controlled contention requires an observed wait and blocker release. Performance and
plans have separate advisory/informational outcomes; missing observations remain explicit.
See [observations.md](observations.md) for the implemented Steps 12–14 boundaries.

## Evidence and results

`RunSpec` declares inputs and deadlines. `OperationResult` records version, phase,
SQLSTATE, and semantic assertions. `Finding` explains a decision with evidence.
`RunResult` keeps `completion`, `verdict`, `coverage`, and `cleanup` separate.

An incomplete experiment may confirm a failure, so `partial` + `fail` is valid.
A passing result requires all declared checks, complete execution, no blocking
findings, no failed operations/assertions, and successful cleanup. Checks need
phase-qualified IDs such as `baseline/deployed-v1/get-user` and
`post_deployed/deployed-v1/get-user`. The implemented analysis validates receipts
and derives coverage from actual observations; caller-supplied completion flags
cannot substitute for missing evidence.

Render terminal, JSON, Markdown, and escaped static HTML from the same result.
Persist reports after cleanup so cleanup status is accurate. Never include secrets
or connection credentials in reports or resource manifests.

Packaged starters use the same validated inputs and pipeline. Saved-result rendering
has no live database access; selected-run cleaning delegates exact ownership and
active-run checks to the host runtime. CI verifies installed wheel/sdist behavior
outside the checkout; see [onboarding.md](onboarding.md) and [ci.md](ci.md).
