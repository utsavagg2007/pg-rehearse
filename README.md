# pg-rehearse

A Python CLI for rehearsing PostgreSQL migrations against old and new application
queries in disposable databases.

**Current stage: disposable runtime and strict SQL preflight implemented.** The CLI can provision
an owned PostgreSQL 17 container on a private network, confirm readiness, and remove
its resources. Durable manifests support recovery after interruption or a crash.
Validation checks typed inputs, contained paths, fixture rows, contract SQL,
supported migration AST shapes, and transaction declarations before allocation.
`run` deliberately exits with code **4 (inconclusive)** until the pipeline exists.

This project was recreated from the requirements visible in the
[shared conversation](https://chatgpt.com/share/6acf9947-f660-83ee-bcea-032862955887).
The original starter archive was not exposed by the public share. The blueprint
PDF supplied afterward has now been reviewed, including runtime boundaries on
pages 7–9 and 30. This is a fresh implementation of that architecture.

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

Start Docker Desktop, then run `pg-rehearse doctor` to check the daemon too.

## Disposable PostgreSQL milestone

```sh
docker pull postgres:17
pg-rehearse sandbox
```

The sandbox command creates an internal network and a database without a published
host port, waits for TCP readiness, and tears everything down. It prints a manifest
path under `.pg-rehearse/runs/<run-id>/manifest.json`. PostgreSQL data lives in a
256 MiB tmpfs, with a 512 MiB memory limit, one CPU, and 128 processes. The image is
resolved before allocation, launched by content ID, and its repository digest is
recorded. Image downloading is explicit and separate from the readiness deadline.

Use `--startup-seconds 30` to change the readiness budget, or `--hold-seconds 30`
to keep the ready environment alive briefly. SIGINT/SIGTERM trigger teardown;
SIGKILL or machine loss require recovery with the recorded manifest:

```sh
pg-rehearse recover --manifest .pg-rehearse/runs/<run-id>/manifest.json
```

Replace `<run-id>` with the actual run ID. Recovery refuses active runs and checks
resource IDs plus ownership labels. It never performs global Docker pruning or
removes foreign network endpoints. Lifecycle success does not establish application
compatibility. See [docs/runtime.md](docs/runtime.md) for the API and failure behavior.

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
make integration
make build
```

Or run the checks individually:

```sh
uv run --locked pytest
uv run --locked pytest --run-docker
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv build
```

Use `.venv/bin/python` as the interpreter in your editor.

## Next complete migration milestone

1. Provision an owned, disposable PostgreSQL 17 instance (**implemented**).
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

`validate` now performs PostgreSQL 17 SQL preflight and typed fixture validation.
Unsupported statements return 4; malformed inputs return 2. Source snapshots and
hashes preserve accepted input. Database compatibility still requires the future
execution pipeline. See [docs/preflight.md](docs/preflight.md) for the exact support
matrix, input limits, parameter rules, and allocation boundary.
