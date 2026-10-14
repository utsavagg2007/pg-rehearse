# Implementation progress

Updated: 2026-10-14 (Asia/Kolkata).

## Current checkpoint

The requested project foundation has been created directly in this folder from
the visible shared conversation. The environment and editable package are ready.
The database execution roadmap remains pending, beginning with Docker lifecycle.

The original uploaded blueprint and downloadable starter archive were not
accessible from the public share. This checkout reconstructs the visible
architecture and examples; it is not a copy of that inaccessible archive.

## Code inventory

| Item | Current amount |
| --- | ---: |
| Functional foundation modules | 5 |
| Version/module entry-point files | 2 |
| Package namespace files | 11 |
| Explicitly planned feature modules | 39 |
| Total Python source files | 57 |
| Physical lines in the five foundation modules | 468 |
| Physical source lines including placeholders and entry points | 690 |
| Unit test files | 4 |
| Physical unit-test lines | 311 |
| Passing unit-test cases | 39 |

Line counts include comments, docstrings, and blank lines. Placeholder counts do
not measure working features. Integration/e2e directories currently contain test
plans, with no real-database test implementations.

## Completed

- Python package in `src/pg_rehearse`, version 0.1.0, installed in editable mode.
- Local Python 3.14.6 environment, runtime/dev dependencies, and `uv.lock`.
- `.venv` compatibility symlink to `venv/`, resolving a macOS hidden-file issue
  that prevented Python from loading the editable-install hook.
- CLI `--help`, `--version`, `doctor`, and structural `validate`.
- Reserved `run` command and direct worker invocation return 4 (inconclusive),
  explicitly declaring the missing database implementation.
- Configuration/evidence models with separate completion, verdict, coverage, and cleanup.
- Safe YAML with duplicate-key rejection; contained relative input paths; unique
  migration and operation IDs; consistent result expectations.
- Orders schema, fixture declarations, deployed/candidate contracts, rename SQL,
  and an additive control example.
- Complete planned module layout, feature order, architecture/decision documents,
  development commands, Dockerfile template, and foundation CI workflow.

## Verification actually performed

| Check | Result |
| --- | --- |
| Foundation unit tests | 39 passed |
| Ruff lint | Passed |
| Ruff formatting | Passed |
| mypy strict checks | Passed for 57 source files |
| Source distribution and wheel build | Passed |
| Built-wheel CLI outside the source checkout | Passed; reused existing dependency installation |
| CLI version | `pg-rehearse 0.1.0` |
| Python/dependency doctor | Passed |
| Rename and control configuration validation | Both passed |
| Locked offline environment sync | Passed; package remained importable |
| Dependency lock consistency | Passed |
| Full environment doctor | Exit 3: Docker daemon is stopped/unavailable |

The CI workflow is configured, but has not been run on GitHub. Docker image
building, resource lifecycle, and SQL execution have not been verified. No
compatibility verdict or database report has been fabricated.

## Remaining boundaries

Configuration validation currently checks structure and files. SQL parsing/support
classification and typed fixture-row validation are still pending. RunResult
models guard obvious invalid passing results; the future analysis layer must
match coverage claims to actual evidence.

All database provisioning, role isolation, seed loading, query execution,
migrations, analysis, reports, clones, rollout experiments, application probes,
lock/performance/plan observation, onboarding, evaluation, and external pilot work
remain pending. See `IMPLEMENTATION_ORDER.md` for acceptance criteria for all 19
features.

## Next implementation

**Feature 1: Docker provisioning, ownership, cleanup, and recovery.** Start Docker
Desktop, implement the host runtime and resource manifest, and verify success,
partial allocation, readiness timeout, interruption recovery, and ownership-safe
cleanup against real containers. Update this file with evidence before marking
that feature complete.

## Maintenance rule

Update this file after every implementation change. Recount affected files/lines,
record the tests actually run, state current limitations, and identify the next
feature. Keep partial roadmap steps partial until their acceptance criteria pass.
