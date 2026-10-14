# Orders example

`rehearsal.yml` describes the first compatibility failure: renaming `users.name`
to `users.full_name` should preserve data but break the deployed version's
`get-user` query. The candidate query uses the new column name. The old
`list-orders` query should continue working.

`control.yml` adds a nullable column without changing deployed queries. It should
pass once database execution and complete coverage are implemented.

Paths in each rehearsal file are relative to its directory. Query parameters
follow Psycopg's `%s` binding syntax; the future runner must bind values rather
than interpolate SQL. Expected rows include explicit `ORDER BY` clauses for
deterministic comparisons.

The seed fixture has two users and two orders. The fixture row model and loader
are still pending. All examples can be validated for structure today:

```sh
uv run --locked pg-rehearse validate --config examples/orders/rehearsal.yml
uv run --locked pg-rehearse validate --config examples/orders/control.yml
```

No database result is claimed yet. Actual v1/v2 application probes will be added
under `apps/` in feature 10.
