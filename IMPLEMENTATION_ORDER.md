# Implementation order

Updated: 2026-10-15. Features 1 and 2 are implemented and verified. Features 3–19
remain pending or partial. Follow this sequence from the shared conversation.
Update `PROGRESS.md` as each acceptance criterion is actually verified.

## 1. Docker provisioning, ownership, cleanup, and recovery

Status: implemented. Use `pg-rehearse sandbox` and `pg-rehearse recover`.
Real Docker verification is recorded in `PROGRESS.md` and `docs/runtime.md`.

Modules: `runtime/docker.py`, `runtime/manifest.py`, `runtime/cleanup.py`,
`orchestrator.py`.

- Generate a unique run ID; create a dedicated network and PostgreSQL 17 container.
- Attach ownership labels to every resource; persist IDs atomically as allocation proceeds.
- Enforce readiness deadlines; record startup errors without leaking credentials.
- Use guaranteed cleanup on successful runs, exceptions, timeouts, and interruptions.
- Recover interrupted runs by checking both saved resource IDs and ownership labels.

Acceptance: real Docker tests show successful allocation and removal, bounded
readiness failure, cleanup after partial allocation, refusal to remove unrelated
resources, and recovery after coordinator interruption. Record cleanup failures.

## 2. Strict configuration, path validation, and SQL preflight

Status: implemented. `validate` performs complete preflight without Docker, and
`validated_environment` gates rehearsal provisioning on that result. See
`docs/preflight.md` for the bounded SQL matrix and `PROGRESS.md` for test evidence.

Modules: `config.py`, `models.py`, `migration/preflight.py`, `migration/classify.py`.

- Extend the existing YAML validation with typed fixture models and explicit supported fields.
- Parse PostgreSQL SQL; classify supported operations rather than relying on substring checks.
- Reject path escapes and unsupported inputs before allocating runtime resources.
- Validate transaction mode constraints, including concurrent index steps.

Acceptance: malformed YAML, duplicate IDs, escapes, unsupported SQL, and invalid
transaction declarations produce actionable input failures and zero allocations.
Document the support boundary and test the PostgreSQL parser against all examples.

## 3. Isolated worker and scoped database roles

Modules: `worker.py`, `runtime/roles.py`, `docker/worker.Dockerfile`.

- Run the worker on the private run network with no Docker socket or host credentials.
- Separate setup, migration, workload, and observer roles with minimal grants.
- Apply statement and lock deadlines; produce versioned structured worker evidence.
- Reject incomplete worker responses and redact connection credentials.

Acceptance: real isolation tests verify role permissions, absent Docker access,
readiness and execution deadlines, worker crash handling, and no secret leakage.

## 4. Baseline loading and deterministic fixtures

Modules: `fixtures/seed.py`, `config.py`, `models.py`.

- Load schema and validated fixture rows using parameterized statements.
- Make generation deterministic by seed; avoid wall-clock and random global state.
- Respect foreign-key ordering and reset sequences after explicit IDs.

Acceptance: identical inputs reproduce identical fixture data; invalid fixtures
fail as setup errors; schema loading and expected orders rows are verified on PostgreSQL.

## 5. SQL contracts and semantic assertions

Modules: `workload/contracts.py`, `workload/runner.py`, `workload/assertions.py`.

- Execute bound parameters; capture version, phase, SQLSTATE, and per-assertion evidence.
- Check result columns, ordered rows, and row counts; distinguish SQL errors from assertion errors.
- Reset failed transactions and enumerate required checks explicitly.

Acceptance: deployed baseline queries return the expected rows; wrong columns,
values, or counts fail clearly; a failing operation does not poison the next probe.

## 6. Transaction-aware migrations and rename detection

Modules: `migration/executor.py`, `orchestrator.py`.

- Execute declared steps in order with transaction or autocommit boundaries.
- Commit migrations before post-migration queries and preserve failed-step evidence.
- Re-run unchanged deployed contracts; check candidate contracts after the rename.

Acceptance: the rename commits, the deployed query fails with SQLSTATE `42703`,
the candidate query sees the preserved value, and the additive control remains valid.
Classify baseline failures separately; do not blame migrations that never executed.

## 7. Compatibility findings and terminal/JSON/Markdown reports

Modules: `analysis/compatibility.py`, `analysis/coverage.py`, `report/terminal.py`,
`report/json_report.py`, `report/markdown.py`, `cli.py`.

- Turn recorded evidence into findings with stable rule IDs and clear explanations.
- Match coverage claims to actual required evidence; separate completion and verdict.
- Render all formats from the same result after final cleanup status is known.
- Apply documented exit codes and preserve reports for unsuccessful rehearsals.

Acceptance: a complete control exits 0; confirmed incompatibility exits 1; input,
infrastructure, and inconclusive cases exit 2, 3, and 4. Missing evidence never passes.
The report identifies the old query, phase, SQLSTATE, assertion details, and cleanup status.

**First complete product milestone:** features 1–7 produce a real rename rehearsal.

## 8. Immutable templates and fresh database clones

Modules: `fixtures/template.py`, `fixtures/clone.py`.

- Build verified templates keyed by relevant input identity; prevent mutable reuse.
- Close template sessions and create a fresh branch for independent experiments.
- Clean every clone and template owned by the run.

Acceptance: independent branches begin with identical data and cannot influence one
another; stale template identity is rejected; errors and cleanup do not leak clones.

## 9. Deployment phases, persistent sessions, mixed writes, and rollback

Modules: `rollout/phases.py`, `rollout/mixed_writes.py`, `rollout/rollback.py`,
`workload/sessions.py`.

- Declare ordered rollout phases and keep deployed sessions alive across DDL.
- Probe fresh and persistent sessions; commit old/new writes and verify cross-version reads.
- Rehearse declared rollback on a separate branch and retain its coverage.

Acceptance: evidence distinguishes baseline, post-migration, mixed-version, and
rollback behavior. Missing phases remain inconclusive; failed writes and data
incompatibility are visible even when the migration itself succeeds.

## 10. Real old/new application probes

Modules: `rollout/apps.py`, `examples/orders/apps/`.

- Add independently runnable old and new orders application versions.
- Exercise actual query, transaction, and connection lifecycle behavior.
- Capture probe exit status and correlate failures with recorded database evidence.

Acceptance: reproduce a real deployed-version failure and a candidate success;
application probe crashes are distinguished from compatibility findings.

## 11. Complete index and CHECK support alongside rename cases

Modules: `migration/classify.py`, `migration/preflight.py`, `migration/executor.py`.

- Implement index creation/drop cases, concurrent modes, and invalid-index evidence.
- Add CHECK creation/validation and old writes rejected by tightened constraints.
- Expand the documented support matrix and labeled passing/failing examples.

Acceptance: index transaction requirements and invalid build remnants are reported;
a successfully applied CHECK can still produce an old-application write failure.
Unsupported variants cannot receive a passing verdict.

## 12. Controlled contention and lock observation

Modules: `observe/locks.py`, `analysis/locks.py`.

- Introduce reproducible blocker sessions and observe waits from a separate connection.
- Capture blockers, wait events, lock types, deadlines, and observation coverage.
- Bound experiments and dispose of contention sessions reliably.

Acceptance: demonstrate a reproducible lock wait and bounded timeout; distinguish
unobserved locks from observed absence; clean up blockers on every failure path.

## 13. Repeatable advisory performance measurements

Modules: `observe/timings.py`, `benchmarks/runner.py`, `benchmarks/statistics.py`,
`benchmarks/controls.py`, `analysis/performance.py`.

- Use fresh branches, warmups, repeated samples, and unchanged controls.
- Record sample counts, dispersion, environment, and measurement limitations.
- Keep timing findings advisory rather than asserting production equivalence.

Acceptance: reports include raw samples and control measurements; insufficient
evidence cannot become a definitive regression or improvement claim.

## 14. Query-plan capture and comparison

Modules: `observe/plans.py`, `analysis/plans.py`.

- Capture structured plans before and after migration; retain original evidence.
- Normalize incidental differences and compare meaningful operators/estimates.
- Guard execution-capable plan requests and isolate any data-changing statements.

Acceptance: a reproducible index case shows explainable plan changes; unavailable
plans remain explicit; capture does not corrupt other experiment branches.

## 15. Escaped static HTML reports

Modules: `report/html.py`, `report/templates/`.

- Render findings, phase evidence, coverage, plans, and measurements from `RunResult`.
- Escape SQL, errors, identifiers, and all untrusted input content.
- Provide a portable static report without external scripts or credential leakage.

Acceptance: a saved report opens independently, conveys cleanup and uncertainty,
and hostile input is displayed as text rather than executed.

## 16. CLI onboarding: init, demo, report, and clean

Modules: `onboarding/init.py`, `onboarding/demo.py`, `onboarding/clean.py`, `cli.py`.

- Create starter inputs without overwriting existing files.
- Run the real demo, display existing reports, and recover only owned run resources.
- Provide helpful next actions and consistent exit codes.

Acceptance: a new developer can initialize, validate, run, view, and clean a real
rehearsal; existing user files and unrelated Docker resources remain protected.

## 17. CI integration and reproducible packaging

Modules: `.github/workflows/ci.yml`, `pyproject.toml`, `uv.lock`.

- Extend the existing foundation CI with real Docker integration and CLI rehearsals.
- Retain reports even when a rehearsal fails; assert expected incompatible verdicts.
- Test built distributions outside the source checkout and lock supported dependency versions.

Acceptance: clean CI environments reproduce the rename failure and passing control,
publish evidence as job artifacts, and install working wheel/sdist distributions.

## 18. Labeled evaluation and failure-path audit

Modules: `evaluation/`, `tests/integration/`, `tests/e2e/`.

- Add labeled compatible, incompatible, unsupported, and inconclusive cases.
- Inject lifecycle, SQL, worker, report-writing, cleanup, and interruption failures.
- Audit false passes, false failures, missing coverage, and resource leaks.

Acceptance: labels match real evidence, every critical failure path is exercised,
and incomplete or unsupported runs cannot silently pass.

## 19. External developer pilot and release preparation

Modules: documentation, packaging, release notes, pilot records.

- Have developers outside the project reproduce the quickstart and useful failures.
- Fix onboarding problems; document support boundaries and known limitations.
- Prepare versioned release notes, upgrade guidance, and a reproducible release checklist.

Acceptance: external developers independently obtain expected results and recover
from documented failures; release artifacts match verified source and lockfiles.
This stage requires actual participant feedback, not simulated pilot results.
