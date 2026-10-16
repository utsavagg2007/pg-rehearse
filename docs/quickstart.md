# Quickstart

The development environment is `.venv` in the project root. Activate it with
`source .venv/bin/activate`, or use `uv run --locked` for each command.

```sh
pg-rehearse --version
pg-rehearse doctor --skip-docker
pg-rehearse validate --config examples/orders/rehearsal.yml
```

`doctor --skip-docker` only verifies Python and dependencies. Start Docker Desktop
and run `pg-rehearse doctor` for the daemon check. No containers are provisioned.

Prepare Docker and build the worker before checking isolated execution:

```sh
docker pull postgres:17
make worker-image
pg-rehearse run --config examples/orders/rehearsal.yml
```

The rename example returns **1**: the old query fails with SQLSTATE 42703, while
candidate queries read preserved data. The additive control returns **0**:

```sh
pg-rehearse run --config examples/orders/control.yml
```

The printed run directory contains final `report.json`, `report.md` and `report.html`. Setup,
baseline or infrastructure failures return **3**; incomplete evidence returns **4**.
See `docs/rehearsal.md` for transaction, clone, reporting and cleanup behavior.

To install in another checkout, install Python 3.12+ and uv, then run
`uv sync --locked`. The interpreter selection is recorded in `.python-version`;
use `--python 3.12` to override it. Dependencies install locally into `.venv`.

In this checkout `.venv` is a symlink to `venv/`. A hidden filesystem flag on the
original environment prevented Python from processing its editable-install hooks.
Moving the environment to a visible directory fixed package imports; both
directories are excluded from version control. If recreating an environment on
this Mac produces the same issue, run `export UV_PROJECT_ENVIRONMENT=venv` before
`uv sync --locked`, and keep it set for later `uv run` commands in that shell.

The disposable runtime is implemented. Start Docker Desktop, then run:

```sh
docker pull postgres:17
pg-rehearse sandbox
```

The command verifies readiness and removes its own database and network. The
printed manifest records resource IDs, image identity, and cleanup status. Use
`pg-rehearse recover --manifest <printed-manifest-path>` after a hard crash.
See `docs/runtime.md` for supported options, deadlines, and failure behavior.

Step 2 is also implemented: `validate` parses PostgreSQL 17 SQL, validates fixture
rows and paths, and checks migration support and transaction modes. No Docker
resources are allocated by validation. See `docs/preflight.md` for accepted inputs.

Steps 1–17 are implemented. Workers retain separate setup/migration/workload/observer
permissions. Templates and fresh branches isolate independent experiments. Optional rollout declarations add persistent sessions, committed mixed writes
and separate application rollback. Use applications.yml for real HTTP probes and
see docs/rollout.md for index/CHECK evidence. Use contention.yml, benchmark.yml and plans.yml for the optional Steps 12–14
experiments; see [observations.md](observations.md) for their evidence and limits.

To start with your own new directory, run `pg-rehearse init my-rehearsal`, then
validate `my-rehearsal/rehearsal.yml`. `pg-rehearse demo` runs the real rename
without requiring a source checkout; its expected exit is 1. Open the printed HTML
report directly, or regenerate it using
`pg-rehearse report <report.json> --format html` (same saved exit code).
`pg-rehearse clean --run-id <run-id>` retries cleanup of one inactive owned run
and retains evidence. See [onboarding.md](onboarding.md) and [ci.md](ci.md).
