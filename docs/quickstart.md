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

```sh
pg-rehearse run --config examples/orders/rehearsal.yml
```

This currently returns **4**, explicitly reporting that the migration run
pipeline has not been implemented. Validation does not prove SQL compatibility.

To install in another checkout, install Python 3.12+ and uv, then run
`uv sync --locked`. The interpreter selection is recorded in `.python-version`;
use `--python 3.12` to override it. Dependencies install locally into `.venv`.

In this checkout `.venv` is a symlink to `venv/`. A hidden filesystem flag on the
original environment prevented Python from processing its editable-install hooks.
Moving the environment to a visible directory fixed package imports; both
directories are excluded from version control. If recreating an environment on
this Mac produces the same issue, use `UV_PROJECT_ENVIRONMENT=venv uv sync --locked`
and activate `venv/bin/activate`.

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

Next, follow feature 3 in `IMPLEMENTATION_ORDER.md`: isolated workers and scoped
database roles. Once features 1–7 work, the rename example should produce
SQLSTATE `42703`, a compatibility failure, and exit code 1; the additive control
should pass with exit code 0.
