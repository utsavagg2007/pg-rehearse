# Project layout

Updated: 2026-10-16. Steps 1–11 implement the runtime, preflight, scoped workers, migrations, reports, immutable clones, rollout phases and real HTTP reference apps.

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
│   ├── cli.py                     doctor, validate, sandbox, recover, complete SQL rehearsal via run
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
│   └── apps/                      Independently runnable old/new reference HTTP applications
├── tests/
│   ├── unit/                      259 unit cases across twelve files
│   ├── integration/               75 real PostgreSQL cases across seven files
│   └── e2e/                       CLI verification reference
├── docker/worker.Dockerfile        Locked nonroot worker image build
├── docs/
│   ├── quickstart.md
│   ├── architecture.md
│   ├── runtime.md                 Lifecycle API, CLI, recovery, limits
│   ├── preflight.md               SQL matrix, strict inputs, allocation gate
│   ├── worker.md                  Worker protocol, permissions and deadlines
│   ├── baseline.md                Baseline loading, probes and semantic assertions
│   ├── rehearsal.md               Migration/clone lifecycle, findings and final reports
│   ├── rollout.md                 Phases, HTTP applications, index/CHECK facts and limits
│   └── decisions/                 Foundation and verified runtime ADRs
├── benchmarks/                    Performance acceptance plan
├── evaluation/                    Labeled-case acceptance plan
└── .github/workflows/ci.yml        Python 3.12/3.14 preflight, runtime and worker CI
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

## Planned modules

Each of these 14 modules is explicitly labeled as a placeholder. Docstrings
describe responsibilities; they are not working feature implementations. The
remaining modules do not execute database features.

| Module | Feature order | Responsibility |
| --- | --- | --- |
| `analysis/locks.py` | 12 | Interpret observed waits and blockers without treating absent evidence as success. |
| `analysis/performance.py` | 13 | Generate advisory findings from repeated measurements and unchanged controls. |
| `analysis/plans.py` | 14 | Compare normalized query plans while preserving the original captured evidence. |
| `report/html.py` | 15 | Render escaped static HTML without executing embedded input content. |
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
15. Benchmark suites and broader labeled evaluation inputs will be added with their
corresponding features. Avoid empty implementation claims.

