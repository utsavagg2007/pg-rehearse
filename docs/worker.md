# Isolated worker and scoped roles

Step 3 is implemented. `run` preflights inputs, provisions PostgreSQL, bootstraps
four scoped logins and starts the worker on the run's internal network. The worker
checks copied input hashes and probes real database permissions. The coordinator
validates its response and cleans up the worker, database and network.

Steps 4–8 load schema/fixtures, seal a template and execute independent baseline,
deployed and candidate experiments through this boundary. See [baseline.md](baseline.md)
and [rehearsal.md](rehearsal.md) for migration commits, findings and final reports.

## Build and run

```sh
docker pull postgres:17
docker build -f docker/worker.Dockerfile -t pg-rehearse-worker:0.1.0 .
uv run --locked pg-rehearse run --config examples/orders/rehearsal.yml
```

Rebuild after source or lockfile changes. Runs never pull or build images. A missing
image is an infrastructure error. The worker uses locked dependencies; its resolved
immutable image content ID is recorded as `worker_image_id` in the run manifest.

## Database permissions

| Login | Allowed work | Boundary |
| --- | --- | --- |
| `rehearse_setup` | Explicitly SET ROLE to the migration owner for setup/seeding | Baseline objects belong to the migration owner; no cluster administration |
| `rehearse_migration` | Own public and rehearsal tables; accepted DDL | No superuser, database/role creation, replication or RLS bypass |
| `rehearse_workload` | Table SELECT/INSERT/UPDATE/DELETE and sequence USAGE | No schema creation, ownership, TRUNCATE or migration membership |
| `rehearse_observer` | Schema USAGE and pg_read_all_stats | No application table grants or writes; default read-only transactions |

All logins lack database CREATE/TEMP and server-file/program privileges. PUBLIC
access to the rehearsal database/schema is revoked, as is PUBLIC connectivity to
postgres/template1. Default grants cover objects created by the migration owner.
`worker.connect_as(request, "setup")` explicitly switches to that owner, so setup
deliberately has DDL authority through membership. It is not an application login.
The observer uses the narrower statistics role rather than pg_monitor; see
[PostgreSQL 17 roles](https://www.postgresql.org/docs/17/predefined-roles.html).

The host sends only fixed trusted bootstrap declarations through local psql stdin
via Docker exec. User SQL and input paths never enter that administrative call.
Worker connections use Psycopg and scoped passwords. The PostgreSQL bootstrap
password is never sent to the worker. Docker authority stays in host runtime code;
analysis remains independent of live database connections.

## Container and input boundary

The worker runs as UID/GID 10001 with a read-only root filesystem, all capabilities
dropped, no-new-privileges, one CPU, 256 MiB memory, 64 processes and a 16 MiB /tmp.
It has one internal network, no host mounts, Docker socket, published ports or host
process namespace. Host proxy configuration is not copied. Docker logs rotate at
16 MiB. Docker administrators retain control; this is not a hostile-code sandbox.

A versioned JSON request arrives through stdin, not environment variables,
arguments or a host file. It contains the fixed experiment task and run-scoped database name, copied accepted
bytes, relative names, hashes, timeouts and four ephemeral passwords. Inputs are limited to 1 MiB each and 8 MiB
combined, enforced before allocation. The worker rechecks hashes without reopening
host paths. Passwords mask ordinary representations; only explicit stdin
serialization reveals them. Requests and raw error messages are never persisted.

## Deadlines and evidence

PostgreSQL readiness retains startup_seconds. Trusted bootstrap has a separate
ten-second budget. Scoped connections bound connection establishment and set
statement_ms, lock_ms and idle transaction deadlines. The supported SQL preflight
rejects session changes. These PostgreSQL settings are user-settable, so they are
reinforced by independent process and coordinator deadlines, rather than treated
as privilege barriers. See [PostgreSQL 17 settings](https://www.postgresql.org/docs/17/runtime-config-client.html).

`timeouts.worker_seconds` defaults to 60 (integer 1–3600). For a complete rehearsal
the host budget covers all bootstrap/clone calls and workers, including allocation,
start, input delivery, execution and response collection. The
worker also bounds input reads and execution with an alarm. A stuck/crashed worker
triggers owned teardown, with the existing separate cleanup budget. Statement
timeout (57014) and lock timeout (55P03) remain distinct database evidence.

Requests and safe failure envelopes retain version 1. Version-2 responses must match the run and every input hash, contain exactly one
probe per role, and show expected identities, privileges, PostgreSQL major and
deadlines. Unknown fields, missing/duplicate evidence, malformed JSON, nonzero
exits and oversized output cannot succeed. Errors expose fixed categories and
optional SQLSTATE; raw stderr, connection text and passwords are excluded.

Validated task receipts are saved privately as seed-evidence.json, worker-evidence.json
(baseline), post_deployed-evidence.json and optional post_candidate-evidence.json.
Optional rollout-evidence.json and rollback-evidence.json retain session, commit,
phase-barrier and reference HTTP application evidence. Each completion field
describes that task only. Version-2 responses also validate
experiment identity, initial fixture evidence, ordered migration digests/commit
flags and phase-specific contract assertions. Final cleanup stays in manifest.json;
report.json/report.md keep completion, verdict, coverage and cleanup separate.
A crashed worker cannot supply completed evidence; earlier valid receipts remain.
Recovery verifies ownership of recorded IDs or unsaved-ID intents, then removes
all workers before PostgreSQL and the network. Manifest experiment slots retain
separate allocation intents and IDs; old single-worker manifests remain readable.

## Verification

Run `make worker-image`, then `uv run --locked pytest --run-docker`. Real tests use
the production image and PostgreSQL 17 for grants/denials, statistics access,
nonroot execution, container isolation, statement/lock/Python/host deadlines,
authentication failure/redaction, crashes, invalid evidence, output limits, lost
allocation responses, recovery and ownership refusal. Fixed test-only SQL verifies
these primitives. Baseline/contract tests also verify real schema and fixture
loading, assertions, rollback isolation and recovery after failures.

Optional diagnostic tasks retain contention-evidence.json, benchmark_<trial>_<arm>-evidence.json,
plan_baseline-evidence.json and plan_candidate-evidence.json. Trial and arm identities
are validated in requests, database names, manifest slots and receipts. Contention
validates sampled actor/barrier evidence; benchmarks validate the exact warmup and
attempt schedule; plans validate analyze consent, original tree and commit state.
Raw plan receipts are private and may contain literals; shared summaries normalize
expressions. See [observations.md](observations.md). Finished benchmark databases
have an additional exact ownership marker checked before early host-only release.
