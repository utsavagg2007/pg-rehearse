# Project layout

Updated: 2026-10-14. The project is in the foundation stage.

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
│   ├── cli.py                     doctor, validate, reserved run, version, help
│   ├── config.py                  YAML, path and contract validation
│   ├── models.py                  Configuration and evidence contracts
│   ├── doctor.py                  Read-only environment diagnostics
│   ├── errors.py                  Failure types and exit-code contract
│   ├── orchestrator.py            Planned coordinator
│   ├── worker.py                  Planned worker; refuses execution today
│   ├── runtime/                   Provisioning, ownership, cleanup, roles
│   ├── fixtures/                  Seed, immutable templates, fresh clones
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
│   ├── migrations/                Rename and additive control SQL
│   └── apps/                      Real application probes planned for feature 10
├── tests/
│   ├── unit/                      39 tests across four files
│   ├── integration/               Documented real-PostgreSQL test plan
│   └── e2e/                       Documented complete-CLI test plan
├── docker/worker.Dockerfile        Foundation worker build template
├── docs/
│   ├── quickstart.md
│   ├── architecture.md
│   └── decisions/                 Accepted foundation and planned runtime ADRs
├── benchmarks/                    Performance acceptance plan
├── evaluation/                    Labeled-case acceptance plan
└── .github/workflows/ci.yml        Python 3.12/3.14 foundation CI
```

## Implemented modules

| Module | Working responsibility |
| --- | --- |
| `cli.py` | Help/version, read-only diagnostics, structural input validation, inconclusive run boundary |
| `config.py` | Safe YAML, duplicate-key rejection, contained relative paths, existing files, contract loading |
| `models.py` | Run inputs, query expectations, recorded operation evidence, coverage, verdict and cleanup contracts |
| `doctor.py` | Python/dependency versions and bounded Docker daemon probe |
| `errors.py` | Shared exceptions and stable exit codes |
| `__init__.py`, `__main__.py` | Version and module entry point |

The eleven package `__init__.py` files establish namespaces. They do not implement
database features.

## Planned modules

Each of these 39 modules is explicitly labeled as a placeholder. Docstrings
describe responsibilities; they are not working feature implementations. The
worker additionally exits inconclusive when invoked directly.

| Module | Feature order | Responsibility |
| --- | --- | --- |
| `orchestrator.py` | 1–7 | Coordinate validation, resource provisioning, worker execution, evidence, reports, and cleanup. |
| `worker.py` | 3–7 | Execute experiments inside the run network with scoped database credentials and no Docker socket. |
| `runtime/docker.py` | 1 | Provision labeled PostgreSQL 17 containers and per-run networks; enforce bounded readiness. |
| `runtime/manifest.py` | 1 | Persist run IDs and resource IDs atomically without storing credentials. |
| `runtime/cleanup.py` | 1 | Verify ownership before removal and support interrupted-run recovery. |
| `runtime/roles.py` | 3 | Create narrowly scoped setup, migration, workload, and observer database roles. |
| `fixtures/seed.py` | 4 | Load baseline schemas and validated deterministic fixture data. |
| `fixtures/clone.py` | 8 | Create independent database clones with no active template sessions. |
| `fixtures/template.py` | 8 | Build and verify immutable templates keyed by schema and fixture identity. |
| `migration/executor.py` | 6 | Execute ordered migration steps with declared transaction modes and error rollback. |
| `migration/preflight.py` | 2 | Parse and classify supported SQL before allocating any runtime resources. |
| `migration/classify.py` | 2, 11 | Classify rename, index, and CHECK operations with unsupported-input evidence. |
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

