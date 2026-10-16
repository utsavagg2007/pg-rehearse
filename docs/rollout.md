# Rollout sessions, application probes and index/CHECK evidence

Steps 9–11 extend the existing rehearsal without changing SQL-only configurations.
Rebuild the worker after source changes; the locked environment needs no new dependency.

```sh
make worker-image
pg-rehearse run --config examples/orders/rollout.yml
pg-rehearse run --config examples/orders/applications.yml
pg-rehearse run --config examples/orders/applications-status-failure.yml
pg-rehearse run --config examples/orders/check-tightening.yml
pg-rehearse run --config examples/orders/index-drop.yml
```

Expected results:

| Configuration | Exit | Observed behavior |
| --- | --- | --- |
| `rollout.yml` | 0 | Old/new committed writes, cross-version reads, candidate target and application rollback |
| `rollout-rename.yml` | 1 | Persistent and fresh old SQL fail with 42703 after committed rename |
| `applications.yml` | 0 | Real old/new HTTP processes pass all 13 application probes |
| `applications-rename.yml` | 1 | Old HTTP reads fail with 42703; candidate reads the preserved value |
| `applications-status-failure.yml` | 1 | SQL passes, but old application rejects the candidate's committed processing status |
| `check-tightening.yml` | 1 | NOT VALID CHECK commits but rejects a previously valid old write with 23514 |
| `index-drop.yml` | 0 | Ordinary index creation and concurrent drop retain verified catalog evidence |

## Explicit schema-first rollout

The optional `rollout` object declares `persistent_old_sessions` (1–4) and exactly
three ordered `phases`: mixed_versions, candidate_only, app_rollback. Each phase
contains bounded `operations`, using the existing SQL/parameters/expect format plus
`actor: deployed` or `actor: candidate`. All declared rollout actions are required.
See `examples/orders/rollout.yml` for a complete copyable declaration.

The supported mixed schedule has four actions: deployed write, candidate read,
candidate write, deployed read. The rollback schedule has a candidate write and a
deployed read. The candidate-only phase contains candidate operations. Preflight
validates operation identities, actors, phase ordering, SQL support and bound
parameters before resource allocation. Other rollout strategies are rejected.

The worker opens the old connections before DDL, verifies their baseline behavior,
and holds them open without an idle transaction. After migration commit, it probes
those same PostgreSQL backends and then fresh old connections. Receipts retain
actor and backend PID. The coordinator rejects changed persistent identities or a
fresh probe that reused an old backend. Old SQL connections close before the
candidate-only phase.

Mixed and rollback writes use real transactions. Success is recorded only after
assertions and commit. A failed write assertion rolls back the write and skips its
dependent reads. A successful committed write remains committed even if the next
read fails. The candidate target sees the mixed branch's committed data. Rollback
runs on a different baseline clone, reapplies the forward migration, commits the
declared candidate write and tests the deployed read against that data. This is
**application rollback on the migrated schema**, not a database down-migration.

Phase records include observed check IDs, completion and the established barrier:
verified baseline, migration commit or completed committed-write sequence. Missing
required phases or commits cannot pass. Individual query failures roll back before
another independent probe. There is no fabricated claim of traffic during DDL:
these tests establish before/after barriers and live old sessions, while controlled
in-migration contention and observations remain feature 12.

## Maintained HTTP reference application

`applications` enables the fixed `orders` adapter and requires a rollout declaration:

```yaml
applications:
  adapter: orders
  user_id: 7
  expected_name: Ada
  order_id_base: 9000
  candidate_status: pending
```

The reference apps are ordinary Python HTTP services using Psycopg and the standard
library, with independent entry points at `examples/orders/apps/deployed.py` and
`candidate.py`. No new web framework or arbitrary host hook is introduced. Both
versions expose GET /users/id, GET /orders/id and POST /orders. The old version reads
users.name and validates the old status vocabulary. The candidate reads full_name
and additionally accepts processing. POST commits before replying; GET validates
and serializes application/domain values rather than replaying a SQL contract.

The compatible fixture deliberately starts with both name columns and tests an
additive index. It does not implement user-name dual writes or certify an expand/
contract migration. The rename fixture uses the original schema and demonstrates
old read breakage. The status fixture exposes a semantic rollback failure even
when every declared SQL contract succeeds.

Applications run as separate subprocesses inside the owned, immutable worker image,
on its private network, under its nonroot/read-only restrictions and resource budget.
Their HTTP listeners bind only worker loopback; they publish no host port. The
worker starts the old service before DDL and keeps its process and prepared database
connection alive across the migration. Fresh old and candidate services start after
commit. Readiness is only a lifecycle gate; real HTTP assertions provide coverage.
The adapter exercises both write/read directions, stops old application traffic for
the target probe, and tests rollback after a candidate POST on the separate branch.

Child stdin receives only the workload connection settings. No password appears in
argv/environment, and no app receives migration/setup credentials or Docker access.
Revision evidence combines the fixed deployed/candidate label with a digest of the
application implementation; the worker image content ID is recorded by the host.
These are maintained reference revisions, not provenance for a user's deployed app.

Probe results retain phase, application revision, process/backend identities, HTTP
status, optional process exit status, SQLSTATE and semantic assertions. Unknown JSON,
wrong revisions or pool identities, missing assertions, process crashes and deadlines
cannot succeed. Application domain failures and SQL errors remain distinct from
adapter/process failures. Readiness is bounded to five seconds, each HTTP request
uses `timeouts.application_ms` (default 5000), and the entire worker pipeline retains
its existing worker_seconds deadline. All child groups are stopped on every exit;
forced worker/container teardown also removes them.

The adapter reserves order_id_base+1/+2/+3 on its two independent branches; fixture
collisions and invalid column values are rejected during preflight. Declared SQL
rollout actions should leave these IDs available. SQL-only reports retain the
sql_contract evidence level and never claim application execution. HTTP-tested
reports add reference_application alongside explicit required/completed coverage.

## Catalog evidence and bounded index/CHECK support

Every migration step captures public-table columns, index definitions/columns/sort
options/validity/readiness, and named CHECK definitions/validation state before and
after execution. Failed steps also attempt a final snapshot, preserving partial
concurrent-index effects. Pure analysis verifies final declared catalog effects;
missing or inconsistent observations prevent a pass.

Supported index SQL remains named non-unique B-tree creation on plain columns,
ordinary or concurrent. DROP INDEX targets one index explicitly created by an
earlier migration, with optional public qualification, RESTRICT semantics and
ordinary/concurrent modes. Concurrent create/drop require a single autocommit
statement. IF EXISTS/IF NOT EXISTS, UNIQUE, expressions, partial indexes, CASCADE,
constraint-owned indexes and other schemas remain unsupported.

Named CHECK add, NOT VALID, VALIDATE and explicit drop/re-add are supported. NOT VALID
skips old-row validation but still enforces new writes; validation can fail on old
fixture rows. Replacement must be explicit DDL and respects transaction boundaries.
Catalog definitions and validation state are retained even when SQL/application
behavior later fails. An observed invalid index produces INVALID_INDEX_REMAINS;
a timeout does not become a compatibility failure merely because such an artifact
exists. No failed build is automatically retried on a dirty branch.

See [PostgreSQL 17 CREATE INDEX](https://www.postgresql.org/docs/17/sql-createindex.html),
[DROP INDEX](https://www.postgresql.org/docs/17/sql-dropindex.html) and
[ALTER TABLE](https://www.postgresql.org/docs/17/sql-altertable.html).

## Limits

This milestone supports the declared SQL schedule and the maintained orders HTTP
adapter. App-first deployments, arbitrary application images, database rollback,
HTTP authentication, a full production pool, lock certification and performance
claims are outside this scope. DML RETURNING still uses libpq buffering. Worker
receipts retain the existing 8 MiB limit; large catalog histories can hit that bound.
A worker killed before its task receipt is finalized loses that task's unfinished
observations; earlier branch receipts and final missing coverage remain visible.
