# Release notes

## 0.1.0 — prepared, unpublished

Initial PostgreSQL 17 migration rehearsal CLI. No release publication or external
developer pilot acceptance is claimed. See [release preparation](docs/release.md)
for verification and upgrade guidance.

- Disposable, privately networked PostgreSQL and scoped workers with deadlines,
  immutable fixture templates, fresh experiment clones and ownership-safe recovery.
- Strict YAML/path/fixture validation and PostgreSQL AST preflight before resource
  allocation. Supported migrations cover bounded column renames, ordinary and
  concurrent B-tree index operations, and named CHECK lifecycle operations.
- Deployed/candidate SQL contracts, typed semantic assertions, schema-first rollout,
  persistent/fresh sessions, committed mixed writes, application rollback and
  maintained HTTP application probes.
- Controlled contention observations, advisory repeated performance trials with
  unchanged controls, and isolated sanitized query-plan comparisons.
- Separate completion, compatibility verdict, required coverage and cleanup fields;
  final terminal/JSON/Markdown/escaped static HTML evidence and documented exit codes.
- Non-overwriting `init`, real rename `demo`, bounded saved `report` rendering and
  selected-run `clean`; locked packaging and real installed-distribution checks.
- Labeled evaluation and failure-path checks; release and independent pilot
  instructions. Actual verification and remaining work are recorded in
  [PROGRESS.md](PROGRESS.md).

### Support and limits

Python 3.12+ and Docker are required for rehearsals. Prepare the official PostgreSQL
17 image and matching worker explicitly. See [RUNNING.md](RUNNING.md).

This version supports the documented SQL subset and schema-first application
rollback. It does not execute database down-migrations, arbitrary DDL/traffic replay
or external application images. Unsupported inputs remain inconclusive before
allocation. Missing required evidence cannot pass. Performance is advisory and
plan differences are informational; synthetic fixtures do not certify production
capacity or complete application compatibility.

Reports intentionally contain SQL and fixture values. Keep sensitive evidence
private. Filesystem loss can prevent report persistence; selected-run recovery
retains ownership checks. There is no earlier stable-version migration guarantee.
