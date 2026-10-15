# Project layout

Updated: 2026-10-15. The disposable runtime and PostgreSQL 17 input preflight are implemented.

```text
pg-rehearse/
├── pyproject.toml                 Package, dependencies, tools, CLI entry point
├── uv.lock                        Exact resolved dependency versions
├── .python-version                Local Python 3.14 selection
├── .venv -> venv/                  Local editable development environment
├── README.md                      Setup and current capability
├── AGENTS.md                      Instructions for future implementation work
├── PROGRESS.md                    Measured code status and verification
├── IMPLEMENTATION_ORDER.md        Ordered feature roadmap and acceptance criteria
├── PROJECT_LAYOUT.md              This module reference
├── CONTRIBUTING.md                Development conventions
├── Makefile                       Setup, checks, formatting, build
├── src/pg_rehearse/
│   ├── __init__.py                Package version
│   ├── __main__.py                python -m pg_rehearse entry point
│   ├── cli.py                     doctor, validate, sandbox, recover, reserved run
│   ├── config.py                  YAML, path and contract validation
│   ├── models.py                  Configuration and evidence contracts
│   ├── doctor.py                  Read-only environment diagnostics
│   ├── errors.py                  Failure types and exit-code contract
│   ├── orchestrator.py            Disposable lifecycle coordinator; full pipeline pending
│   ├── worker.py                  Planned worker; refuses execution today
│   ├── runtime/                   Provisioning, ownership, cleanup, roles
│   ├── fixtures/                  Typed row validation; seed/templates/clones planned
│   ├── migration/                 Preflight, support classification, execution
│   ├── workload/                  Contracts, SQL runner, assertions, sessions
│   ├── analysis/                  Compatibility, coverage, locks, timings, plans
│   ├── report/                    Terminal, JSON, Markdown, HTML
│   ├── rollout/                   Phases, mixed writes, rollback, application probes
│   ├── observe/                   Locks, timings, query plans
│   ├── benchmarks/                Runner, statistics, controls
│   ├── onboarding/                init, demo, owned-resource cleanup
│   └── evaluation/                Labeled case evaluation
├── examples/orders/
│   ├── rehearsal.yml              Intentionally incompatible rename example
│   ├── control.yml                Additive compatibility control
│   ├── schema/base.sql            Users and orders schema
│   ├── fixtures/orders.yml        Two users and two orders
│   ├── contracts/                 Deployed-v1 and candidate-v2 query contracts
│   ├── migrations/                Rename and supported B-tree control SQL
│   ├── unsupported/               Rejected ADD COLUMN counterexample
│   └── apps/                      Real application probes planned for feature 10
├── tests/
│   ├── unit/                      155 unit cases across eight files
│   ├── integration/               17 real PostgreSQL cases across three files
│   └── e2e/                       Documented complete-CLI test plan
├── docker/worker.Dockerfile        Foundation worker build template
├── docs/
│   ├── quickstart.md
│   ├── architecture.md
│   ├── runtime.md                 Lifecycle API, CLI, recovery, limits
│   ├── preflight.md               SQL matrix, strict inputs, allocation gate
│   └── decisions/                 Foundation and verified runtime ADRs
├── benchmarks/                    Performance acceptance plan
├── evaluation/                    Labeled-case acceptance plan
└── .github/workflows/ci.yml        Python 3.12/3.14 unit and runtime CI
```

## Implemented modules

| Module | Working responsibility |
| --- | --- |
| `cli.py` | Help/version, diagnostics, full input preflight, sandbox lifecycle, recovery, inconclusive run boundary |
| `config.py` | Strict bounded YAML and file snapshots, typed fixture validation, SQL preflight and hashes |
| `models.py` | Run inputs, query expectations, recorded operation evidence, coverage, verdict and cleanup contracts |
| `doctor.py` | Python/dependency versions and bounded Docker daemon probe |
| `errors.py` | Shared exceptions and stable exit codes |
| `orchestrator.py` | Validated allocation gate, sandbox lifecycle and signals; full migration pipeline pending |
| `runtime/docker.py` | PG17 image resolution, internal network, bounded readiness, temporary storage, lifecycle context |
| `runtime/manifest.py` | Atomic allocation intents/IDs and active-run locking |
| `runtime/cleanup.py` | Ownership-checked teardown and explicit crash recovery |
| `migration/preflight.py` | PostgreSQL 17 AST parsing, spans, source hashes, binding checks |
| `migration/classify.py` | Baseline catalog and bounded migration/contract SQL classification |
| `fixtures/validate.py` | Typed rows, required values, key uniqueness, and fixture parent references |
| `__init__.py`, `__main__.py` | Version and module entry point |

The eleven package `__init__.py` files establish namespaces. They do not implement
database features.

## Planned modules

Each of these 33 modules is explicitly labeled as a placeholder. Docstrings
describe responsibilities; they are not working feature implementations. The
worker additionally exits inconclusive when invoked directly.

| Module | Feature order | Responsibility |
| --- | --- | --- |
| `worker.py` | 3–7 | Execute experiments inside the run network with scoped database credentials and no Docker socket. |
| `runtime/roles.py` | 3 | Create narrowly scoped setup, migration, workload, and observer database roles. |
| `fixtures/seed.py` | 4 | Load baseline schemas and validated deterministic fixture data. |
| `fixtures/clone.py` | 8 | Create independent database clones with no active template sessions. |
| `fixtures/template.py` | 8 | Build and verify immutable templates keyed by schema and fixture identity. |
| `migration/executor.py` | 6 | Execute ordered migration steps with declared transaction modes and error rollback. |
| `workload/contracts.py` | 5 | Prepare query contracts for execution and phase-qualified coverage. |
| `workload/runner.py` | 5 | Execute parameterized operations with deadlines and capture SQLSTATE. |
| `workload/assertions.py` | 5 | Compare returned columns, rows, and row counts against semantic expectations. |
| `workload/sessions.py` | 9 | Preserve deployed sessions across DDL and contrast them with fresh sessions. |
| `analysis/compatibility.py` | 7 | Distinguish baseline errors from migration-caused incompatibility using recorded evidence. |
| `analysis/coverage.py` | 7 | Match required check IDs to actual evidence and prevent incomplete runs from passing. |
| `analysis/locks.py` | 12 | Interpret observed waits and blockers without treating absent evidence as success. |
| `analysis/performance.py` | 13 | Generate advisory findings from repeated measurements and unchanged controls. |
| `analysis/plans.py` | 14 | Compare normalized query plans while preserving the original captured evidence. |
| `report/terminal.py` | 7 | Render run findings and coverage in a concise Rich terminal report. |
| `report/json_report.py` | 7 | Write versioned machine-readable results including the final cleanup status. |
| `report/markdown.py` | 7 | Render a shareable Markdown summary from the same RunResult. |
| `report/html.py` | 15 | Render escaped static HTML without executing embedded input content. |
| `rollout/phases.py` | 9 | Declare and run baseline, migration, mixed-version, and completed deployment phases. |
| `rollout/mixed_writes.py` | 9 | Commit old and new version writes and verify cross-version reads. |
| `rollout/rollback.py` | 9 | Rehearse declared rollback behavior on an independent branch. |
| `rollout/apps.py` | 10 | Run real application probes and retain version-specific evidence. |
| `observe/locks.py` | 12 | Observe lock waits through a separate connection under controlled contention. |
| `observe/timings.py` | 13 | Capture warmups and repeated operation timings with run context. |
| `observe/plans.py` | 14 | Capture PostgreSQL query plans with explicit execution consent in the isolated runtime. |
| `benchmarks/runner.py` | 13 | Run repeatable baseline and candidate measurement groups on fresh branches. |
| `benchmarks/statistics.py` | 13 | Summarize sample counts and dispersion without claiming unsupported precision. |
| `benchmarks/controls.py` | 13 | Measure unchanged controls to identify environmental variation. |
| `onboarding/init.py` | 16 | Create a validated starter project without overwriting existing user files. |
| `onboarding/demo.py` | 16 | Run the real rename demonstration once the complete pipeline is available. |
| `onboarding/clean.py` | 16 | Expose run-scoped resource recovery using ownership-checked runtime cleanup. |
| `evaluation/cases.py` | 18 | Compare labeled migration cases and lifecycle fault injections against actual results. |

The HTML template directory will be added with its first actual template in feature
15. Real application code, benchmark suites, and labeled evaluation inputs will be
added with their corresponding features. Avoid empty implementation claims.

