# pg-rehearse

A Python CLI for rehearsing PostgreSQL migrations against old and new application
queries in disposable databases.

**Current stage: project foundation.** The local environment, CLI diagnostics,
configuration models, input validation, examples, tests, and module layout are
implemented. Docker provisioning and database execution are the next features.
`run` deliberately exits with code **4 (inconclusive)** until the pipeline exists.

This project was recreated from the requirements visible in the
[shared conversation](https://chatgpt.com/share/6acf9947-f660-83ee-bcea-032862955887).
The original uploaded blueprint and downloadable starter files were not exposed
by the public share; this is a fresh implementation of the documented structure.

## Use the environment

The local `.venv` is already created and the package is installed in editable mode.
On this Mac, `.venv` points to `venv/` to avoid a filesystem visibility issue that
caused Python to skip editable-install hooks. The activation command is unchanged.

```sh
cd /Users/utsavaggarwal/Documents/pg-rehearse
source .venv/bin/activate
pg-rehearse --help
pg-rehearse --version
pg-rehearse doctor --skip-docker
pg-rehearse validate --config examples/orders/rehearsal.yml
```

Start Docker Desktop, then run `pg-rehearse doctor` to check the daemon too. Docker
is only checked for availability; the foundation never creates containers.

To recreate the environment with [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked
uv run --locked pg-rehearse doctor
```

The project supports Python 3.12+. This checkout selects Python 3.14 to use the
interpreter already installed locally. `uv sync --locked --python 3.12` selects
3.12 instead. `uv.lock` records exact dependency versions.

## Development

```sh
make check
make build
```

Or run the checks individually:

```sh
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv build
```

Use `.venv/bin/python` as the interpreter in your editor.

## First useful database milestone

1. Provision an owned, disposable PostgreSQL 17 instance.
2. Load the orders schema and deterministic fixtures.
3. Verify the deployed application's queries and semantic assertions.
4. Commit the `users.name` → `users.full_name` rename.
5. Demonstrate that an unchanged old query fails with SQLSTATE `42703`.
6. Write evidence-backed reports and clean up all resources for the run.

The rename example is intentionally incompatible. The additive control example
will provide a passing comparison once the execution pipeline is implemented.
Neither result is simulated by this scaffold.

## Project references

- [PROGRESS.md](PROGRESS.md): implemented code, verification, limitations, next task.
- [PROJECT_LAYOUT.md](PROJECT_LAYOUT.md): modules and their responsibilities.
- [IMPLEMENTATION_ORDER.md](IMPLEMENTATION_ORDER.md): 19 ordered features and acceptance criteria.
- [docs/quickstart.md](docs/quickstart.md): setup and first commands.
- [docs/architecture.md](docs/architecture.md): coordinator, worker, evidence, and isolation design.
- [CONTRIBUTING.md](CONTRIBUTING.md): development conventions.

## CLI exit codes

| Code | Meaning |
| --- | --- |
| 0 | Command successful; future runs require complete passing evidence and cleanup |
| 1 | Confirmed compatibility failure |
| 2 | Invalid configuration or CLI input |
| 3 | Environment/infrastructure failure |
| 4 | Inconclusive or feature not implemented |

Configuration validation checks YAML structure, unique IDs, result expectations,
existing files, and path containment. It does **not** parse SQL, verify SQL support,
validate fixture row schemas, or establish database compatibility.
