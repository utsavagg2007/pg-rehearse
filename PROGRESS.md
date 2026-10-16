# Implementation progress

Updated: 2026-10-16 (Asia/Kolkata).

## Current checkpoint

**Steps 1–11 are implemented.** The disposable PostgreSQL rehearsal now supports
strict preflight, scoped workers, verified templates/clones, committed migrations,
semantic SQL assertions, final reports, explicit schema-first rollout sessions,
committed mixed-version writes, independent application rollback, real maintained
old/new HTTP probes and index/CHECK catalog verification.

The final regression passed **334 tests**, including **259 unit cases** and **75
real PostgreSQL cases**, in **340.10 seconds**, against the rebuilt worker. Lint,
formatting, strict types, the offline lock check and distribution builds passed.
Existing SQL-only configurations retain their original results.

All user SQL and reference HTTP processes stay in the worker pipeline. The host
retains Docker and fixed trusted bootstrap/clone declarations. Analysis uses only
accepted inputs and retained observations. Completion, verdict, coverage and cleanup
remain separate. Missing catalog, session, commit, phase or app evidence never passes.
No dependencies were added; the locked environment remains in place.

## Steps 6–8 reverified before this work

Docker was initially stopped; the first integration attempt could not connect.
Docker Desktop was started, then all **291 existing cases passed in 192.06s**,
including **58 real PostgreSQL cases**. Lint, formatting and strict types passed.
Evidence: `.pg-rehearse/step6-8-recheck.xml`.

Existing rename/control behavior remains: committed rename breaks unchanged old
SQL with 42703 while candidate reads Ada; ordinary index control passes. Owned
private Docker resources, readiness/deadlines, scoped roles, copied input snapshots,
atomic fixtures, rollback-only probes, deterministic digests, final cleanup/reporting
and crash recovery remain covered by the full suite.

## Step 9: declared rollout, persistent sessions, committed writes and rollback

- Optional rollout declarations require a candidate contract and bounded, ordered
  mixed_versions, candidate_only and app_rollback phases. Actor IDs, operation IDs,
  supported SQL, required actions and write/read ordering are checked before Docker.
- One to four old workload connections open and pass baseline probes before DDL.
  They stay alive without an idle transaction across migration commit. Persistent
  post-probes retain the same backend PIDs; fresh old probes use another connection.
- The mixed sequence commits an old write, checks a candidate read, commits a new
  write and checks an old read. Assertions must pass before write commit. A failed
  write assertion rolls back and skips dependent reads. A committed write survives
  a later failing read; real follow-up queries verified both behaviors.
- Old SQL connections close before candidate-only actions, which see the committed
  mixed data. Application rollback uses another immutable-baseline clone, forward
  migration, committed candidate write and deployed read of that data. It does not
  reset to S0 or silently perform a database down-migration.
- Phase records retain check IDs, completion and actual baseline/migration/commit
  barriers. The receipt validator rejects replaced persistent sessions, fake commit
  flags, inconsistent phase claims and invented coverage. Missing required execution
  evidence remains inconclusive, even when other branches passed.
- Existing SQL-only configurations retain their original flow and do not claim
  rollout/application coverage. No app-first, generic workflow or rollback engine
  was introduced.

## Step 10: real old/new reference application probes

- Added independently runnable deployed/candidate orders entry points and a small
  real HTTP application using Psycopg and the standard library. Fixed revision-specific
  queries, request validation, domain status validation, serialization, prepared
  connection reuse and POST commit happen inside actual application processes.
- The built-in adapter launches separate services inside the owned immutable worker
  image, with loopback HTTP, nonroot/read-only restrictions and the existing resource
  budget. Child stdin receives only workload credentials; no Docker socket, host
  hooks, setup/migration secrets or passwords in argv/environment are supplied.
- The old service/pool remains alive across DDL. Fresh old and candidate processes
  start after commit. Real HTTP probes check user values, both committed order
  write/read directions, candidate-only state and rollback after candidate POST.
- Results retain source revision digest, actor, process/backend identities, HTTP
  status, process exit status when available, SQLSTATE and semantic assertions.
  Readiness alone is not coverage; altered revisions, missing assertions and
  malformed output cannot pass. SQL-only and reference_application evidence levels
  remain explicit beside required/completed coverage.
- Application requests use application_ms (default 5000), readiness is bounded to
  five seconds, and the entire pipeline retains worker_seconds. Child groups stop
  on normal completion/errors; owned worker/container teardown handles forced exits.
- The compatible HTTP fixture passes all 13 probes. The rename reproduces old HTTP
  42703 while the candidate succeeds. The new-status fixture passes every SQL check
  but old HTTP domain parsing rejects committed processing data with 422, including
  application rollback. These are real application outcomes, not SQL replay badges.
- Real injected process SIGKILL (-9), malformed HTTP output and delayed HTTP requests
  produce distinct infrastructure/inconclusive evidence, with successful cleanup.
- Fixed adapter declarations reject missing reference columns, reserved order ID
  fixture collisions and invalid ID values before allocation. Arbitrary app images,
  a production web stack and concurrent pool certification remain outside this scope.

## Step 11: complete bounded index/CHECK execution evidence

- Each migration captures public columns, index definitions/columns/sort flags/
  validity/readiness and CHECK definitions/validation state before and after execution.
  Failed steps attempt a final snapshot. Pure analysis verifies final declared effects,
  including an index and column rename in one transaction. Missing/wrong catalog
  observations are missing coverage, never a passing check.
- Added DROP INDEX for one explicitly created index, with optional public qualification,
  RESTRICT semantics and ordinary/concurrent modes. Concurrent create/drop retain
  the single-autocommit-statement restriction. Unique, expression, partial, covering,
  non-B-tree, constraint-owned and arbitrary-schema indexes remain unsupported.
- Named CHECK add/NOT VALID/VALIDATE/drop/re-add execute with original transaction
  declarations. Tests verify validation state and definitions, successful replacement,
  validation failure on existing zero-value rows and old-write rejection with 23514.
- A real blocked concurrent non-unique index build retained an invalid pg_index entry;
  its facts and INVALID_INDEX_REMAINS finding survive the failure. Timeout remains
  inconclusive; the branch is disposed without automatically retrying dirty state.
- Reports include SQL/application findings, actor/phase evidence and catalog snapshots.
  Old-version SQL failures in persistent/fresh/mixed phases use deployed finding IDs.

## Verification actually performed

| Check | Result |
| --- | --- |
| Pre-change Step 6–8 recheck | **291 passed in 192.06 seconds** |
| Initial new real rollout/catalog cases | **12 passed in 115.43 seconds** |
| Complete regression before final field/label corrections | **331 passed in 350.74 seconds** |
| Final full regression | **334 passed in 340.10 seconds** |
| Final unit suite | **259 passed in 4.41 seconds** |
| Real PostgreSQL cases | 75: 13 lifecycle, 4 preflight, 14 worker, 14 baseline, 13 rehearsal, 17 rollout/apps/catalog |
| Ruff lint / formatting / strict mypy | Passed; 64 source files type-checked |
| Locked dependencies | Consistent offline, 42 packages; no new dependency |
| Worker image | Rebuilt from final source; exercised by the full suite and final CLI demos |
| Wheel and source distribution | Built successfully offline |
| Real initial CLI runs | Rollout 0; HTTP application 0; tightened CHECK 1; cleanup complete |
| Final managed Docker resource inventory | **Zero managed containers and zero managed networks** |

The new real cases cover labeled SQL/HTTP rename/control/domain failures; persistent
and fresh session identity; committed writes and dependent read behavior; independent
rollback; strict receipt mutation rejection; missing required phases; NOT VALID and
VALIDATE/drop/re-add; concurrent index remnants; same-step index+rename; app process
crash, malformed HTTP and request timeout. Existing lifecycle, ownership, input,
worker permission/secret and cleanup fault cases remain in the complete suite.

Local evidence:
- `.pg-rehearse/step6-8-recheck.xml`: verification before pipeline edits.
- `.pg-rehearse/step9-11-new.xml`: first twelve new real cases.
- `.pg-rehearse/step9-11-test-results.xml`: complete regression result.
- `.pg-rehearse/runs/0f7ef97777b84003a632f1a77ef7bbb9/`: initial passing SQL rollout.
- `.pg-rehearse/runs/af2bb90c3d23440ab7f5b77c43a456d0/`: final passing HTTP application report.
- `.pg-rehearse/runs/13082a16e94f4dddbb98c608da8af9d4/`: final application domain/rollback failure with passing SQL.
- `.pg-rehearse/runs/8a2f8e8486e04a428848d3822ab95d55/`: initial CHECK old-write failure.

Verified locally on Docker Desktop 29.7.2, Linux arm64 PG17, host Python 3.14.6 and
worker Python 3.14.8. Official PG image digest:
`postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3`.
Final exercised worker image:
`sha256:aba3e74a6afb4eee411bff4d79970151d773227029dcad88c315bdc2cfe3446a`.
GitHub CI is configured for the complete suite on Python 3.12/3.14 but has not run
in this chat. The supplied architecture PDF is unchanged.

## Code inventory

| Item | Current amount |
| --- | ---: |
| Modules with working behavior | 37 |
| Version/module entry-point files | 2 |
| Package namespace files | 11 |
| Planned feature modules | 14 |
| Total Python source files | 64 |
| Physical working-module lines | 5613 |
| Physical source lines including placeholders | 5702 |
| Unit files / cases | 12 / 259 |
| Physical unit-test lines | 1732 |
| Integration files / cases | 7 / 75 |
| Physical integration-test lines | 1958 |

Two independently runnable example application entry points are outside src.
Physical lines include comments, docstrings and blank lines. PROJECT_LAYOUT.md
lists implemented responsibilities and remaining placeholders.

## Remaining boundaries and next task

**Step 12: controlled contention and lock observation.** Add reproducible blockers,
separate observation and explicit lock coverage without claiming observed absence
from missing samples. The new index timeout test is a test-only failure injection,
not product lock certification. Performance, plans, HTML, onboarding and release
milestones remain later work.

The implemented rollout is explicitly schema-first with a bounded declared sequence.
Application rollback keeps S1 and committed candidate data; database down-migrations
and app-first deployment are unsupported. Reference HTTP apps are maintained demos,
not evidence for a user's production application or release provenance. The compatible
fixture has both user-name columns and does not implement general dual writes.

There are no claimed in-migration requests; old processes/sessions remain alive
across a committed barrier and before/after behavior is observed. Each reference
service uses one prepared connection and shares the worker's memory/CPU budget.
DML RETURNING still buffers in libpq, and sequence advancement persists between
operations within a branch. Explicit assertions and current resource/result limits
remain the supported envelope.

Receipts retain the 8 MiB cap; large catalog histories can exceed it. A process killed
before task receipt finalization loses that task's unfinished observations; earlier
receipts and missing coverage remain. Filesystem loss may prevent reports. Recovery
updates the manifest; existing reports continue to describe the original cleanup
attempt. No failure or missing observation is silently converted into a pass.
