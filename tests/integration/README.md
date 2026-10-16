# Real PostgreSQL integration tests

Prepare Docker and both images:

```sh
docker pull postgres:17
make worker-image
uv run --locked pytest --run-docker
```

There are 75 real cases across seven files:

- Step 1: 13 lifecycle/fault cases in `test_runtime.py` and `test_runtime_faults.py`.
- Step 2: four accepted rename, ordinary/concurrent index and CHECK cases in `test_preflight.py`.
- Step 3: fourteen isolated-worker cases in `test_worker.py`.
- Steps 4–5: fourteen baseline/contract cases in `test_baseline.py`.
- Steps 6–8: thirteen complete rehearsal/clone/report cases in `test_rehearsal.py`.
- Steps 9–11: seventeen rollout/application/catalog cases in `test_rollout.py`.

Worker cases use the production image and PostgreSQL for actual role grants and
permission denials, nonroot execution, isolation settings, statement/lock/wall
budgets, authentication failure and secret exclusion, crashes, missing/malformed
responses, output limits, allocation intents, ownership refusal and recovery.
Baseline cases load accepted schema/fixtures, verify repeatable data and identity
sequences, run bound contract assertions, roll back writes and recover after SQL
errors, result limits and operation deadlines. Rehearsal cases verify rename/control
CLI outcomes, committed valid ordinary/concurrent indexes, transactional rollback,
ordered/autocommit boundaries, isolated writes/sequences, sealed/stale templates,
worker crashes, lock deadlines, failed report writes and recoverable failed cleanup.

Without `--run-docker`, integration cases explicitly skip. With it, unavailable
Docker or a missing required image fails. CI builds the locked worker before tests.
Rebuild the worker image after source or lockfile changes.

New rollout cases exercise persistent/fresh SQL and HTTP sessions, committed writes
and independent rollback, application domain failures despite passing SQL, strict
receipt rejection, dependent-read skips, CHECK validation/drop/re-add and invalid
concurrent index remnants. Actual child process crashes, malformed HTTP responses
and request deadlines remain distinct from SQL compatibility failures.
