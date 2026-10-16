# Real PostgreSQL integration tests

Prepare Docker and both images:

```sh
docker pull postgres:17
make worker-image
uv run --locked pytest --run-docker
```

There are 97 real cases across ten files, plus seven labeled e2e cases:

- Step 1: 13 lifecycle/fault cases in `test_runtime.py` and `test_runtime_faults.py`.
- Step 2: four accepted rename, ordinary/concurrent index and CHECK cases in `test_preflight.py`.
- Step 3: fourteen isolated-worker cases in `test_worker.py`.
- Steps 4–5: fourteen baseline/contract cases in `test_baseline.py`.
- Steps 6–8/15/18: sixteen complete rehearsal/clone/report cases in `test_rehearsal.py`.
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

Steps 12–14 add thirteen observation cases: sampled migration/probe blocking and
timeout; observer gaps and absent conflicts; natural index plan changes and guarded
write plans; five repeated trial pairs with raw samples and unchanged A/A controls;
committed-write reset and retained timeouts; refusal to drop a changed ownership
marker; composition with real HTTP rollout; and partial sample retention after a lost
measurement connection. Receipts reject forged actors,
barriers, samples, settings and plan execution/commit claims.

Steps 15–16 add HTML to the combined observation flow, both Markdown/HTML write
failure fallbacks, and two real onboarding cases in `test_onboarding.py`: a freshly
initialized control plus the actual failing demo, saved rendering and repeated
cleaning; active-run refusal and preservation of an unrelated test-owned network.
Step 17 separately exercises both installed distributions using
`scripts/check_distributions.py`; it is not counted as additional pytest cases.

Step 18 adds JSON-writer failure, preservation of a confirmed incompatibility when
cleanup also fails, two actual SIGINT/SIGTERM cases arriving first during teardown
in `test_runtime_faults.py`, and two full-rehearsal signal/report/exit cases in
`test_rehearsal_interruptions.py`. The e2e matrix includes six real rehearsals and
one unsupported preflight refusal. All remain opt-in through `--run-docker`.
