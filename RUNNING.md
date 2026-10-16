# Run PostgreSQL migration rehearsals

Run commands from the project root. You need Python 3.12+, uv 0.12.7, and a running
Docker daemon (Docker Desktop on this Mac). Use synthetic or approved test data.
Rehearsals create disposable PostgreSQL 17 databases from the local inputs you
provide. Reports contain SQL and fixture values, so keep sensitive reports private.

## 1. Prepare the environment and images

```sh
cd /Users/utsavaggarwal/Documents/pg-rehearse
uv sync --locked
uv run --locked pg-rehearse doctor
docker pull postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
docker tag postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3 postgres:17
make worker-image
```

Change the first path for another checkout. `uv sync --locked` creates or updates
the environment from `uv.lock`. This checkout's `.venv` points to `venv/`; that is
intentional on this Mac. The commands above work without activating it. If creating
a new environment here has hidden-directory import trouble, run
`export UV_PROJECT_ENVIRONMENT=venv` before `uv sync --locked`; keep that variable
set for subsequent `uv run` commands in this shell.

Finish building before running measurements. Rebuild the worker whenever source or
lockfiles change. Run/demo require the installed PostgreSQL and matching
`pg-rehearse-worker:0.1.0` images; they do not download or build them implicitly.

## 2. Try a real rehearsal

```sh
uv run --locked pg-rehearse demo
```

Expected exit: **1**. This intentionally demonstrates an incompatible rename:
the migration commits, the deployed query fails with SQLSTATE **42703**, and the
candidate reads preserved Ada data. Exit 1 is the useful result of this demo.
Expected failures stop scripts using `set -e`; run these commands separately or
explicitly assert the expected status in automation.

For a passing control:

```sh
uv run --locked pg-rehearse run --config examples/orders/control.yml
```

Expected exit: **0**, complete required evidence and complete cleanup. Each run
prints its run ID and report paths under `.pg-rehearse/runs/<run-id>/`.

## 3. Use your own migration and application queries

```sh
uv run --locked pg-rehearse init my-rehearsal
uv run --locked pg-rehearse validate --config my-rehearsal/rehearsal.yml
```

Init refuses any existing destination, including an empty directory. Edit the
starter files for your case:

| File | What to provide |
| --- | --- |
| `schema/base.sql` | The supported baseline schema before the migration |
| `fixtures/orders.yml` | Deterministic baseline rows, including foreign-key dependencies |
| `contracts/deployed-v1.yml` | Actual deployed SQL, bound parameters and expected columns/rows/counts |
| `contracts/candidate-v2.yml` | Candidate SQL and semantic expectations, when checking a new version |
| `migrations/*.sql` | Ordered supported migration statements |
| `rehearsal.yml` | Input paths, contract versions, ordered migration steps and transaction modes |

Keep referenced paths inside the configuration directory. Match fixtures/contracts
to your schema; a broken baseline is an infrastructure/setup outcome. Validation
parses PostgreSQL 17 SQL and checks inputs before allocating resources. Revalidate
after edits, then run:

```sh
uv run --locked pg-rehearse validate --config my-rehearsal/rehearsal.yml
uv run --locked pg-rehearse run --config my-rehearsal/rehearsal.yml
```

The bounded migration support includes column rename, ordinary/concurrent B-tree
index create/drop, and named CHECK add/validate/drop. Concurrent index steps require
the declared autocommit mode. Unsupported variants return 4 before allocation;
the exact SQL/type/fixture envelope is in [docs/preflight.md](docs/preflight.md).
Declared query assertions determine application compatibility; successful DDL alone
is insufficient. CHECK catalog evidence records identity, definition and validation
state, without independently proving predicate equivalence.

Optional examples, after rebuilding the worker:

```sh
uv run --locked pg-rehearse run --config examples/orders/applications.yml
uv run --locked pg-rehearse run --config examples/orders/contention.yml
uv run --locked pg-rehearse run --config examples/orders/benchmark.yml
uv run --locked pg-rehearse run --config examples/orders/plans.yml
```

These expect compatibility exit 0. See [rollout](docs/rollout.md) and
[observations](docs/observations.md) for session/mixed-write/application rollback,
HTTP probes, controlled waits, advisory timing quality and guarded plan execution.
Timings are advisory and do not establish production capacity or outage duration.

## 4. Read reports and recover an interrupted run

Replace `replace_with_printed_run_id` below with the printed 32-character run ID:

```sh
PGR_RUN_ID=replace_with_printed_run_id
uv run --locked pg-rehearse report ".pg-rehearse/runs/$PGR_RUN_ID/report.json"
uv run --locked pg-rehearse report ".pg-rehearse/runs/$PGR_RUN_ID/report.json" --format html
uv run --locked pg-rehearse clean --run-id "$PGR_RUN_ID"
```

Open the adjacent `report.html` in a browser; it is self-contained and script-free.
JSON, Markdown and HTML contain the final outcome after cleanup. Inspect completion,
verdict, required/missing coverage and cleanup separately. Saved rendering requires
no Docker and preserves the saved run's exit code, including 1 for the rename.

Normal runs automatically remove their owned workers, PostgreSQL and network.
Ctrl+C/SIGTERM attempt bounded cleanup and preserve interruption status (130/143).
After a hard crash, clean selects exactly one inactive owned run and retains its
evidence. It refuses active runs and unrelated resource IDs/labels. Repeating clean
is safe. For a custom `--state-dir`, use the same directory with clean. Recovery can
also select the exact manifest:

```sh
uv run --locked pg-rehearse recover --manifest ".pg-rehearse/runs/$PGR_RUN_ID/manifest.json"
```

Recovery updates the manifest; historical reports retain the original cleanup
outcome. Review cleanup errors and retry that selected run after resolving the
cause. Reports and accepted input snapshots are retained; no global prune is used.

| Exit | Interpretation |
| --- | --- |
| 0 | Complete passing rehearsal with successful cleanup |
| 1 | Confirmed compatibility or migration failure |
| 2 | Invalid configuration/path/CLI input |
| 3 | Setup, environment, report or cleanup failure |
| 4 | Unsupported input or inconclusive required evidence |
| 130 / 143 | SIGINT / SIGTERM interruption |

A confirmed failure can coexist with incomplete execution or failed cleanup. Read
all fields. Missing required evidence never becomes a passing rehearsal. If Docker
or an image is unavailable, start/prepare it and run doctor again. If input is
rejected, fix the reported file/SQL boundary and revalidate before rerunning.

## 5. Verify the tool or prepare a release

```sh
make check
make integration
uv run --locked python scripts/evaluate.py --output .pg-rehearse/evaluation
make package-check
```

Evaluation and package-check output must be new directories; pass `--output` to
their scripts for another run. Evaluation exit 0 means the labeled expectations
matched, including deliberate failures. Package checks build and install wheel/sdist
outside the checkout and run real rename/control rehearsals. Run checks sequentially.
See [evaluation/README.md](evaluation/README.md), [docs/release.md](docs/release.md),
and [PROGRESS.md](PROGRESS.md) for actual verification and release gates. Independent
developer pilot feedback and remote CI results must be recorded before release
acceptance; local tests cannot supply those observations.
