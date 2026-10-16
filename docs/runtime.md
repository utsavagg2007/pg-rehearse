# Disposable PostgreSQL runtime

Features 1–17 are implemented. The host coordinator owns Docker operations; the
isolated workers load fixtures, apply migrations and run scoped contract probes. The runtime's readiness
probe is `pg_isready` over TCP, not an application compatibility check.

## Run the milestone

Start Docker Desktop (or a Linux Docker daemon) and prepare the official image:

```sh
docker pull postgres:17
uv run --locked pg-rehearse sandbox
```

`sandbox` creates a unique run, confirms PostgreSQL readiness, and tears down its
container and network before returning 0. A lifecycle failure returns 3. It does
not execute the orders examples, seed data, apply migrations, or issue a migration
verdict. `run` performs the complete SQL-contract rehearsal, returning 1 for the
rename example and 0 for its control. See [worker.md](worker.md) for permissions
and [rehearsal.md](rehearsal.md) for templates, clones and reports.

Options:

| Option | Default | Purpose |
| --- | --- | --- |
| `--state-dir` | `.pg-rehearse/runs` | Parent directory for durable run records |
| `--startup-seconds` | 60 | Deadline for readiness after container start, maximum 600 |
| `--hold-seconds` | 0 | Optional ready lifetime before automatic teardown, maximum 3600 |
| `--image` | `postgres:17` | Installed official PG17 tag, optionally `tag@sha256:digest` |

Images must already be installed. Downloading is separate from the startup budget;
the runtime never silently pulls an arbitrary image. It resolves the local image,
records its repository digest, image content ID, OS, and architecture, then creates
the container by content ID. CI prepares the verified digest explicitly.

## Ownership and isolation

Each run gets a random ID, ownership nonce, internal bridge network, and one
PostgreSQL container. Both resources carry managed, run, owner, and kind labels.
No database port is published and no Docker socket, host credentials, or host
directory is mounted into PostgreSQL.

Data is mounted as a 256 MiB tmpfs. The container has a 512 MiB memory limit,
one CPU, 128-process limit, `no-new-privileges`, and bounded Docker log rotation.
No persistent or anonymous database volume is needed. Workloads larger than this
initial fixture budget need a later explicit resource configuration.

An ephemeral bootstrap password lives only in memory and the owned container's
environment. It is not exported through `RunEnvironment`, stored in manifests, or
printed by the CLI. Docker administrators can inspect container environments;
this runtime is not a hostile-code security boundary. Separate setup, migration,
workload and observer role grants are implemented in feature 3.

## Durable manifest and crash windows

The existing project convention is retained:
`.pg-rehearse/runs/<run-id>/manifest.json`. The manifest contains image identity,
allocation intents, returned resource IDs, phase/failure classification, and
cleanup status. It never stores database credentials, callback error text, or
full Docker request/log payloads.

Before every allocation, persist its intended name and labels. After creation,
persist the returned ID before proceeding. Writes replace complete JSON files
atomically and fsync the file and directory. Run directories use mode 0700 and
manifest files use mode 0600.

On cleanup, locate the recorded ID. If creation returned no ID, locate only the
exact saved intent name. In both cases, verify every ownership label before
removing the resource. This covers a crash or lost response between Docker create
and saving the returned ID. There is no global resource scan or prune.

## Interruptions and recovery

SIGINT/SIGTERM trigger cleanup and return 130/143. Repeated termination signals
within that cleanup scope do not interrupt teardown a second time. SIGKILL and
machine loss cannot run Python cleanup; the durable manifest remains recoverable.

```sh
uv run --locked pg-rehearse recover --manifest .pg-rehearse/runs/<run-id>/manifest.json
```

Replace `<run-id>` with the actual ID printed by the sandbox command. Recovery is
explicit and limited to that run. A per-run advisory lock refuses recovery while
a coordinator is active and is released by the OS after a crash. The runtime lock
currently supports Linux and macOS.

Remove every verified worker first, then PostgreSQL (including its template and
clones), then the network. Never disconnect foreign
network endpoints or delete attached volumes. A blocked network removal is a
visible cleanup failure; resolve the blocking resource separately and retry the
same recovery command. Already absent resources count as removed, making recovery
idempotent. A failure to write cleanup bookkeeping prevents a successful result
even when physical teardown finishes.

`pg-rehearse clean --run-id <run-id> --state-dir .pg-rehearse/runs` selects the
same manifest through a validated 32-character lowercase hexadecimal run ID. It
rejects symlink run directories/manifests, refuses active runs and uses the existing
ownership checks. It retains all input snapshots, manifests and reports. Cleanup
success returns 0; invalid selection returns 2; failed or active cleanup returns 3.

Readiness HTTP calls use the remaining readiness budget, capped at five seconds.
Cleanup has a separate 30-second budget, with bounded Docker requests. These are
coordinator deadlines; a killed process or unavailable Docker daemon still requires
recovery when the environment becomes available.

## Programmatic lifecycle

```python
from pathlib import Path
from pg_rehearse.runtime.docker import DockerRuntime

with DockerRuntime(state_dir=Path(".pg-rehearse/runs")).provision() as environment:
    print(environment.run_id, environment.manifest_path)
    # runtime.execute_worker uses environment.network_id; no host port is required.
# Owned resources are removed here, including after a body exception.
```

The caller's original exception is preserved if teardown also encounters an error.
Cleanup details remain in the manifest and exception notes. CLI signal handlers
are installed by CLI sandbox/run orchestration, not by this library API.

## Verification

```sh
uv run --locked pytest --run-docker
```

The suite covers this lifecycle, accepted SQL shapes, isolated workers and
baseline/contract execution; actual counts and results are in `../PROGRESS.md`.
Without `--run-docker`, the real tests are explicitly skipped. With the option,
an unavailable daemon or missing image is a failure rather than a silent skip.

Real cases cover readiness and PG17 identity, network/storage/resource settings,
normal teardown, a real SQL error, startup timeout, partial allocation, lost create
response, manifest write failure, allocation-intent recovery, ownership mismatch,
two active runs, an occupied network, SIGINT, SIGTERM, and SIGKILL recovery.

The lifecycle tests use fixed trusted SQL to verify PostgreSQL identity and
teardown after a real SQL failure. Worker tests verify the isolated execution
boundary, migration transactions, clone isolation and post-cleanup reports.
The full suite passed locally on Docker Desktop 29.7.2, Linux arm64 PostgreSQL 17.
GitHub CI is configured, but has not been run in this chat.
