# Implementation progress

Updated: 2026-10-15 (Asia/Kolkata).

## Current checkpoint

**Steps 1 and 2 are complete.** Disposable PostgreSQL provisioning, ownership,
teardown, and recovery are verified. Strict declarations, paths, fixture rows,
PostgreSQL 17 parsing, migration classification, bindings, transaction constraints,
and the validation-before-allocation boundary are implemented.

The full migration rehearsal pipeline is still pending. Supported `validate`
inputs return 0 without a compatibility verdict; `run` still returns 4 until the
worker and execution pipeline exist. Unsupported SQL returns 4; invalid inputs
return 2 before allocation.

## Code inventory

| Item | Current amount |
| --- | ---: |
| Modules with working behavior | 12 |
| Version/module entry-point files | 2 |
| Package namespace files | 11 |
| Planned feature modules | 33 |
| Total Python source files | 58 |
| Physical lines in working modules | 2076 |
| Physical source lines including placeholders | 2268 |
| Unit test files / cases | 8 / 155 |
| Physical unit-test lines | 799 |
| Integration files / cases | 3 / 17 |
| Physical integration-test lines | 384 |
| Complete passing test count | 172 |

Counts include blank lines, comments, and docstrings. Working modules are not
completed product features; full orchestration, SQL execution, and reports remain
pending. The complete implementation order is in `IMPLEMENTATION_ORDER.md`.

## Step 1 confirmed

The saved original checkpoint had 60 passing cases including 13 real integration
cases. Before implementing Step 2, those 13 integration cases were re-run and
passed in 14.23 seconds. They also pass in the final combined suite.

Implemented: official PG17 image resolution and immutable image-ID creation,
recorded digest/platform, owned internal network, no published DB port, temporary
data storage, CPU/memory/process budgets, ephemeral credentials, TCP readiness,
atomic credential-free allocation intents/IDs, active-run locking, bounded cleanup,
SIGINT/SIGTERM teardown, SIGKILL recovery, idempotent retry, and refusal to remove
another run's resources. `sandbox` and `recover` remain functional.

Verified image repository digest:
`postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3`.
The local image is Linux arm64 and Docker Desktop reports 29.7.2.

## Step 2 completed

- Locked `pglast` 7.20, verified to use PostgreSQL 17.7 grammar. AST classification
  replaces substring matching and preserves original migration SQL and source spans.
- Strict YAML/model types, unknown-field and duplicate-key rejection, no aliases or
  merge keys, bounded nesting/files/rows/operations, finite values, UTF-8, and NUL checks.
- Relative contained paths, traversal/Windows-path/control-character rejection,
  symlink containment, directory-descriptor/no-follow reads, regular-file checks,
  bounded nonblocking reads, and SHA-256 input snapshots.
- Baseline table/type declarations and explicit fixture row validation: required
  values, type/range/length checks, NULLability, key duplicates, and missing parent rows.
- Supported direct column renames, named non-unique B-tree indexes (including
  concurrent mode), and named CHECK additions/validation/removal/replacement.
- Rejected unknown statements/options, unsupported setup/DDL, explicit transaction
  control, session identity changes, executable setup, and unmodeled SQL side effects.
- Concurrent indexes require autocommit; every autocommit step contains one statement.
- Contract SQL parsing and positional/named binding validation, including quoted
  identifiers, Unicode identifiers, comments, literals, and parameter count/style.
- `validated_environment` finishes preflight before constructing a Docker runtime.
  Invalid-input tests assert the allocator is never called and no run directory is created.
- `validate` displays classifications and source locations while keeping database
  compatibility explicitly unevaluated. `run` uses the same rejection behavior.
- The passing control now uses a supported ordinary index. The original ADD COLUMN
  SQL is retained under `examples/orders/unsupported/` as a rejected counterexample.

## Verification actually performed

| Check | Result |
| --- | --- |
| Final full suite with `--run-docker` | 172 passed in 22.171 seconds |
| Unit cases | 155 passed |
| Real PostgreSQL/Docker cases | 17 passed |
| Ruff lint and formatting | Passed |
| Strict mypy | Passed for 58 source files |
| Dependency lock consistency | Passed |
| Source distribution and wheel build | Passed |
| Rename/control CLI preflight | Both passed; classifications displayed |
| Step 1 regression | All 13 lifecycle cases passed again |

The four new real cases execute fixed reviewed rename, ordinary index, concurrent
index, and CHECK shapes on PostgreSQL 17 after the validation gate. They verify
syntax/support behavior, not a completed production worker or compatibility runner.
The 13 existing cases cover real readiness/identity/DNS/storage/resource limits,
teardown after SQL errors/timeouts/partial allocation, lost responses, manifest
write failure, recovery, ownership mismatch, two live runs, occupied networks,
SIGINT/SIGTERM, and SIGKILL.

Local evidence:
- `.pg-rehearse/step1-recheck.xml`: Step 1 confirmation before this work.
- `.pg-rehearse/step2-test-results.xml`: final 172-case combined run.
- `.pg-rehearse/runs/c6c10629f7fa48468e84d578706eb98b/manifest.json`: earlier
  successful installed-CLI sandbox receipt with completed cleanup.

CI includes these tests on Python 3.12/3.14 with the verified image digest, but
GitHub jobs have not been run in this chat. The original blueprint PDF supplied
previously remains the architecture reference; it has not been modified.

## Remaining boundaries

The SQL envelope is deliberately bounded and documented in `docs/preflight.md`.
Preflight does not emulate all PostgreSQL type/coercion/collation/catalog semantics,
evaluate general CHECK predicates, load fixture data, execute user queries, or
establish application compatibility. Those checks still require the forthcoming
worker, baseline verification, and evidence pipeline. Accepted snapshots must be
passed forward rather than rereading files after validation.

Worker roles/isolation, seeding, contract execution, migrations, analysis/reports,
clones, rollout phases, application probes, observation, onboarding, evaluation,
and pilot work remain pending. No migration compatibility verdict is fabricated.

## Next implementation

**Step 3: isolated worker and scoped database roles.** Give the worker accepted
input snapshots and only its scoped database credentials; keep Docker authority
and bootstrap secrets in the host coordinator. Verify role grants/denials,
execution deadlines, worker crashes, and credential redaction against PostgreSQL.
Then continue with fixture loading, contract execution, migrations, and reports.

Keep `PROJECT_LAYOUT.md` accurate and update this progress record after every
implementation change with actual checks and remaining work.
