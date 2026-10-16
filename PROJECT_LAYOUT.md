# Project layout

Updated: 2026-10-16. Steps 1–18 implement runtime through labeled evaluation/fault audit. Step 19 release/pilot materials are prepared; external feedback is pending.

```text
pg-rehearse/
├── pyproject.toml                 Package, dependencies, tools, CLI entry point
├── uv.lock                        Exact resolved dependency versions
├── .python-version                Local Python 3.14 selection
├── .venv -> venv/                  Local editable development environment
├── README.md                      Setup and current capability
├── RUNNING.md                     Complete setup, custom rehearsal, reports and recovery guide
├── CHANGELOG.md                   Prepared 0.1.0 notes and support boundaries
├── AGENTS.md                      Instructions for future implementation work
├── PROGRESS.md                    Measured code status and verification
├── IMPLEMENTATION_ORDER.md        Ordered feature roadmap and acceptance criteria
├── PROJECT_LAYOUT.md              This module reference
├── CONTRIBUTING.md                Development conventions
├── Makefile                       Setup, checks, formatting, build
├── src/pg_rehearse/
│   ├── __init__.py                Package version
│   ├── __main__.py                python -m pg_rehearse entry point
│   ├── cli.py                     doctor, validate, sandbox, recover, run, init, demo, report, clean
│   ├── config.py                  YAML, path and contract validation
│   ├── models.py                  Configuration and evidence contracts
│   ├── doctor.py                  Read-only environment diagnostics
│   ├── errors.py                  Failure types and exit-code contract
│   ├── orchestrator.py            Preflight, seed/clone experiments, cleanup and final reports
│   ├── worker.py                  Scoped setup, migrations, contract probes and deadlines
│   ├── worker_protocol.py         Versioned copied inputs and validated worker evidence
│   ├── runtime/                   Provisioning, ownership, cleanup, roles
│   ├── fixtures/                  Typed fixtures, atomic seeding, verified templates and clones
│   ├── migration/                 Preflight, support classification, execution
│   ├── workload/                  Contracts, SQL runner, assertions, sessions
│   ├── analysis/                  Compatibility, coverage, locks, timings, plans
│   ├── report/                    Terminal, JSON, Markdown, HTML
│   │   └── templates/report.html  Self-contained static HTML/CSS, no scripts or remote assets
│   ├── rollout/                   Phases, mixed writes, rollback, application probes
│   ├── observe/                   Locks, timings, query plans
│   ├── benchmarks/                Runner, statistics, controls
│   ├── onboarding/                init, demo, owned-resource cleanup
│   │   └── examples/orders/       Bundled validated rename/control starter assets
│   └── evaluation/                Labeled case evaluation
├── examples/orders/
│   ├── rehearsal.yml              Intentionally incompatible rename example
│   ├── control.yml                Additive compatibility control
│   ├── schema/base.sql            Users and orders schema
│   ├── fixtures/orders.yml        Two users and two orders
│   ├── contracts/                 Deployed-v1 and candidate-v2 query contracts
│   ├── migrations/                Rename and supported B-tree control SQL
│   ├── unsupported/               Rejected ADD COLUMN counterexample
│   └── apps/                      Independently runnable old/new reference HTTP applications
├── tests/
│   ├── unit/                      340 unit cases across eighteen files
│   ├── integration/               97 Docker/PostgreSQL cases across ten files
│   └── e2e/                       Seven labeled cases, including zero-allocation unsupported input
├── docker/worker.Dockerfile        Locked nonroot worker image build
├── scripts/check_distributions.py Installed wheel/sdist isolation, reproducibility and real CLI checks
├── scripts/evaluate.py            Real fixed case matrix, incremental private summaries and reports
├── docs/
│   ├── quickstart.md
│   ├── architecture.md
│   ├── runtime.md                 Lifecycle API, CLI, recovery, limits
│   ├── preflight.md               SQL matrix, strict inputs, allocation gate
│   ├── worker.md                  Worker protocol, permissions and deadlines
│   ├── baseline.md                Baseline loading, probes and semantic assertions
│   ├── rehearsal.md               Migration/clone lifecycle, findings and final reports
│   ├── rollout.md                 Phases, HTTP applications, index/CHECK facts and limits
│   ├── observations.md            Controlled locks, advisory timings, private plan evidence
│   ├── onboarding.md              Starter, real demo, saved reports and selected-run cleanup
│   ├── ci.md                      Read-only CI, artifact boundary and locked distribution checks
│   ├── audit.md                   Code review across all steps, focused fixes and known boundaries
│   ├── release.md                 Source/build verification, upgrade guidance and release checklist
│   ├── pilot.md                   Independent developer protocol and pending feedback record
│   └── decisions/                 Foundation and verified runtime ADRs
├── benchmarks/                    Performance acceptance plan
├── evaluation/                    Case labels, fault-test map and interpretation limits
└── .github/workflows/ci.yml        Python 3.12/3.14 real rehearsals and installed distribution CI
```

## Implemented modules

| Module | Working responsibility |
| --- | --- |
| `cli.py` | Help/version, diagnostics, full input preflight, sandbox lifecycle, recovery, final compatibility reports and documented exit codes |
| `config.py` | Strict bounded YAML and file snapshots, typed fixture validation, SQL preflight and hashes |
| `models.py` | Run inputs, query expectations, recorded operation evidence, coverage, verdict and cleanup contracts |
| `doctor.py` | Python/dependency versions and bounded Docker daemon probe |
| `errors.py` | Shared exceptions and stable exit codes |
| `orchestrator.py` | Validated allocation, complete experiment flow, post-cleanup reports and signals |
| `runtime/docker.py` | PG17 image resolution, internal network, bounded readiness, temporary storage, lifecycle context |
| `runtime/manifest.py` | Atomic allocation intents/IDs and active-run locking |
| `runtime/cleanup.py` | Ownership-checked teardown and explicit crash recovery |
| `migration/preflight.py` | PostgreSQL 17 AST parsing, spans, source hashes, binding checks |
| `migration/classify.py` | Baseline catalog and bounded migration/contract SQL classification |
| `fixtures/validate.py` | Typed rows, required values, key uniqueness, and fixture parent references |
| `worker.py`, `worker_protocol.py` | Isolated role probes, copied inputs, deadlines and evidence protocol (Steps 3–8) |
| `runtime/roles.py`, `runtime/worker.py` | Trusted role/template/clone helpers and bounded owned worker supervision |
| `fixtures/seed.py` | Atomic schema/fixture loading, sequence resets and verified data digest |
| `workload/contracts.py` | Phase-qualified operation IDs and required coverage |
| `workload/runner.py` | Rollback-only probes, deadlines, result limits and SQLSTATE |
| `workload/assertions.py` | Pure typed result normalization and semantic assertions |
| `__init__.py`, `__main__.py` | Version and module entry point |
| `fixtures/template.py`, `fixtures/clone.py` | Run-local template identity, sealing and safe clone declarations; trusted execution stays in runtime |
| `migration/executor.py` | Ordered transaction/autocommit steps, committed outcomes, failed-step evidence |
| `analysis/compatibility.py`, `analysis/coverage.py` | Pure receipt validation, actual coverage and evidence-backed findings/verdict |
| `report/terminal.py`, `report/json_report.py`, `report/markdown.py` | Final post-cleanup terminal and private atomic report files |
| `migration/catalog.py` | Worker catalog snapshots and pure verification of rename/index/CHECK effects |
| `workload/sessions.py` | Persistent workload connections held without open transactions across DDL |
| `rollout/phases.py`, `rollout/validation.py` | Declared phase plans, session/commit/application validation and required coverage |
| `rollout/runner.py`, `rollout/mixed_writes.py`, `rollout/rollback.py` | Worker timeline, committed cross-version actions and independent application rollback |
| `rollout/apps.py`, `rollout/orders_app.py` | Fixed HTTP application subprocess adapter, business validation and process/revision evidence |

The eleven package `__init__.py` files establish namespaces. They do not implement
database features.

## Steps 12–14 modules

| Module | Responsibility |
| --- | --- |
| `observe/runner.py`, `observe/validation.py` | Worker diagnostic dispatch and pure receipt checks for actor barriers, schedules and execution consent |
| `observe/locks.py`, `analysis/locks.py` | Four scoped contention actors, separate observer, retained waits and required lock coverage |
| `observe/timings.py`, `benchmarks/runner.py` | Sequential committed workload timings, identical schedules and environment capture |
| `benchmarks/statistics.py`, `benchmarks/controls.py`, `analysis/performance.py` | Descriptive samples, unchanged A/A controls and conservative advisory quality gates |
| `observe/plans.py`, `analysis/plans.py` | Separate bounded EXPLAIN capture, private raw facts and sanitized versioned structural comparison |

The benchmark example, contention release/timeout examples and plan fixture/configuration
are under `examples/orders/`. No dependency was added.

## Steps 15–17 modules

| Module | Responsibility |
| --- | --- |
| `report/html.py`, `report/templates/report.html` | Escaped, portable HTML over the final RunResult, with coverage and uncertainty visible |
| `report/json_report.py` | Bounded saved-result validation and existing private atomic writers |
| `onboarding/init.py`, `onboarding/examples/orders/` | Exclusive starter creation and preflight from packaged resources |
| `onboarding/demo.py` | Temporary starter through the real rehearsal pipeline, retained evidence and expected failure |
| `onboarding/clean.py` | Validated single-run selection delegated to ownership-checked host recovery |
| `scripts/check_distributions.py`, CI workflow | Identical sdist rebuild, isolated installs, real expected-failure/control checks and selected artifacts |

## Steps 18–19

`evaluation/cases.py` defines seven fixed labels and compares real exit, completion,
verdict, coverage, cleanup and rule/SQLSTATE evidence without influencing product
analysis. `scripts/evaluate.py` runs that matrix and retains each report plus summary.
Release/pilot preparation is documentation; actual external sessions remain pending.

No source placeholders remain. There are 66 Python source files: 53 working modules,
two version/entry-point files and eleven namespace files. Verification totals and
local evidence are recorded in PROGRESS.md.
