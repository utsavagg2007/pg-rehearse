# Orders example

`rehearsal.yml` describes the first compatibility failure: renaming `users.name`
to `users.full_name` should preserve data but break the deployed version's
`get-user` query. The candidate query uses the new column name. The old
`list-orders` query should continue working.

`control.yml` adds a non-unique B-tree index without changing deployed queries. It should
pass once database execution and complete coverage are implemented.

Paths in each rehearsal file are relative to its directory. Query parameters
follow Psycopg's `%s` or `%(name)s` binding syntax; the future runner must bind values rather
than interpolate SQL. Expected rows include explicit `ORDER BY` clauses for
deterministic comparisons.

The seed fixture has two users and two orders. Its row types, keys, and parent
references are validated before allocation; database loading remains pending.
The active examples can be fully preflighted today:

```sh
uv run --locked pg-rehearse validate --config examples/orders/rehearsal.yml
uv run --locked pg-rehearse validate --config examples/orders/control.yml
```

No database result is claimed yet. Actual v1/v2 application probes will be added
under `apps/` in feature 10.

`unsupported/add_order_note.sql` retains the original ADD COLUMN example as a
rejected counterexample; that DDL lies outside the initial rename/index/CHECK
support boundary. See `docs/preflight.md` in the repository for the complete matrix.
