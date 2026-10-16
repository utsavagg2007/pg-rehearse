# Migration rehearsal and isolated branches

Steps 6–8 complete the first SQL-contract rehearsal. Prepare PostgreSQL and rebuild
the worker from this checkout, then run:

```sh
docker pull postgres:17
make worker-image
pg-rehearse run --config examples/orders/rehearsal.yml
# Expected exit 1: the deployed get-user query fails with SQLSTATE 42703.
pg-rehearse run --config examples/orders/control.yml
# Expected exit 0: the additive index preserves the deployed contract.
```

The rename is intentionally incompatible. Candidate queries still read the
preserved Ada value. The report proves the declared contract behavior on the
fixture data; it does not establish production or full rollout compatibility.

## Execution order and privileges

1. Complete strict preflight and copy the accepted bytes before allocating Docker.
2. Bootstrap scoped roles and seed/verify the baseline inside a worker.
3. Close setup sessions and seal the baseline database against new connections.
4. Clone a fresh baseline branch, verify its fixture digest, and run the unchanged
   deployed contract. A failing baseline stops all migration experiments.
5. Clone another branch, verify its initial data, apply the migrations and run the
   deployed contract against the committed schema.
6. If configured, clone a separate candidate branch and independently apply the
   same migrations before running the candidate contract.
7. Remove all owned workers, PostgreSQL and the network. Analyze retained evidence
   and write terminal, JSON and Markdown reports with final cleanup status.

Docker and administrative database operations stay in host runtime code. The
trusted helper executes fixed role/template/clone declarations through local psql;
user schema, fixtures, migrations and contracts run only through scoped worker
connections. No worker receives CREATEDB, a bootstrap password or a Docker socket.
The same worker image content ID is used throughout a run.

## Migration boundaries

Steps execute in configuration order. `transaction` wraps every statement in that
step in one transaction; success is recorded only after commit. A failure rolls
back that step. Earlier committed steps remain visible. `autocommit` retains the
existing preflight restriction of exactly one statement, including CREATE INDEX
CONCURRENTLY. A failed step stops subsequent steps and post-migration probes on
that branch. The independent candidate branch retains its own evidence.

Each step records its phase, ID, transaction mode, accepted source digest, statement
count, executed count, commit status, error category and SQLSTATE. Executed count
is the number of statements that returned successfully, not the number committed:
a transactional step may execute one statement and then roll the whole step back.
A failing autocommit operation may leave PostgreSQL artifacts; those are confined
to its disposable branch. Step 11 captures invalid-index/catalog evidence; see [rollout.md](rollout.md).

Every contract operation retains its rollback-only semantics. Writes and sequence
advances within one experiment cannot change another branch. Probe-to-probe
sequence advances within a single contract still persist; committed rollout writes
and persistent sessions are available through the Step 9 rollout declaration.

## Template identity and cleanup

Templates are run-local, with no cross-run cache. Identity hashes the format
version, resolved PostgreSQL image content ID, accepted schema/fixture bytes and
seed. Contract or migration edits do not change fixture identity. The verified
fixture digest is recorded separately.

After seeding, the trusted helper records run/owner/identity in the database comment,
disables connections and terminates remaining template sessions. Clone creation
checks the stored identity, owner and sealed catalog state. Stale receipts or
changed catalog markers are rejected before creating a branch. Every branch
rechecks fixture values/counts before probes or DDL.

Database-level permissions are not copied by CREATE DATABASE, so the helper revokes
PUBLIC access and reapplies the four scoped CONNECT grants on each clone. Connection
settings explicitly reapply statement, lock and idle transaction deadlines. Schema,
object owners, default privileges and sequence state come from the template. See
[PostgreSQL 17 CREATE DATABASE](https://www.postgresql.org/docs/17/sql-createdatabase.html)
and [template databases](https://www.postgresql.org/docs/17/manage-ag-templatedbs.html).

The template and all branches live entirely inside the owned PostgreSQL container's
tmpfs. Ownership-checked container removal destroys them together, including after
partial clone creation, worker crashes and SQL errors. Crash recovery follows the
manifest's exact worker/container IDs or allocation intents and ownership labels;
it does not enumerate or delete databases on another server. Worker records use
one fixed experiment slot each. Old manifests without slots remain recoverable.

`worker_seconds` bounds the whole seed/clone/experiment pipeline, including worker
allocation and response collection. Trusted helper calls use at most ten seconds
and cannot extend the remaining pipeline budget. PostgreSQL startup and final
cleanup retain separate budgets.

## Analysis and reports

Analysis uses accepted inputs and recorded evidence only. It validates receipts,
recomputes expected coverage and checks template/branch digests. Coverage records
observed attempts, including failures. Completion, verdict, coverage and cleanup
remain separate. Missing or inconsistent evidence cannot pass.

Stable rule IDs identify baseline setup/probe failures, failed migrations, deployed
or candidate SQL errors, semantic assertion mismatches, missing/invalid evidence,
inconclusive execution, infrastructure errors, cleanup failures and report errors.
A verified baseline plus a post-migration required assertion mismatch or SQLSTATE
class 22/23/42 confirms a failure. Timeouts, lock waits, result limits and unavailable
evidence remain inconclusive; connection failures are infrastructure errors.
Baseline failures return infrastructure status and never blame unexecuted DDL.
Optional failed checks remain visible and conservatively prevent a passing run.

| Exit | Meaning |
| --- | --- |
| 0 | Complete passing contract evidence and successful cleanup |
| 1 | Confirmed compatibility or migration-application failure |
| 2 | Invalid input, before allocation |
| 3 | Baseline/infrastructure, report-writing or cleanup failure |
| 4 | Unsupported input or inconclusive execution/evidence |

A confirmed failure retains exit 1 even if later infrastructure/cleanup also fails;
those separate fields and findings remain visible. SIGINT/SIGTERM retain 130/143,
with partial reports when the coordinator can finish cleanup and persistence.

Run files live under `.pg-rehearse/runs/<run-id>/`:

- `manifest.json`: allocation intents/IDs, image identity and final cleanup.
- `seed-evidence.json`: seed verification and scoped role checks.
- `worker-evidence.json`: baseline branch evidence (also the existing baseline API receipt).
- `post_deployed-evidence.json`, `post_candidate-evidence.json`: completed branch receipts.
- `report.json`, `report.md`, `report.html`: the same final RunResult used by terminal output.

Files use mode 0600 inside a private run directory. Reports are atomically replaced;
Markdown escapes text and fences recorded evidence. Credentials and raw server
exceptions are excluded. SQL and expected/actual fixture values are intentional
report evidence, so keep reports private if the supplied fixtures are sensitive.
A failed report write returns 3; all formats are retried with an updated infrastructure
outcome, and an unrecoverable stale format is removed when storage permits. Filesystem loss can prevent reports, leaving existing
manifest/worker receipts for diagnosis. Interrupted cleanup can be retried with
`pg-rehearse recover --manifest <path>`; existing reports describe the original run,
while the recovered manifest records the later cleanup attempt.

HTML is self-contained and script-free, escapes all data, embeds no remote assets,
and includes findings, coverage, phases, SQL/HTTP assertions, lock observations,
advisory timing samples, sanitized plan comparisons and environment identities.
Native disclosure controls, table captions, visible keyboard focus and print styles
keep the static evidence usable. Private raw plan trees stay in worker receipts.
Rendering a saved JSON with `pg-rehearse report <path> --format html` does not rerun
or recertify the evidence; it retains the saved exit code. See [onboarding.md](onboarding.md).

## Optional observation branches

[Steps 12–14](observations.md) add a required controlled-contention branch when
selected, sequential advisory benchmark trial arms and separate plan clones.
Compatibility coverage includes required wait/release observations. Performance
sample sufficiency/noise and plan availability are reported in their own fields;
advisory insufficiency does not claim a performance pass. Informational findings
and advisory warnings can accompany complete passing compatibility evidence.
