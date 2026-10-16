# Orders examples

All paths resolve relative to each configuration. Strict preflight runs before
Docker allocation; the worker executes copied input snapshots with bound parameters.

| Config | Expected exit | Purpose |
| --- | --- | --- |
| rehearsal.yml | 1 | Rename preserves Ada but breaks old SQL with 42703 |
| control.yml | 0 | Additive non-unique B-tree index |
| rollout.yml | 0 | Persistent/fresh sessions, committed mixed writes, target and rollback |
| rollout-rename.yml | 1 | Persistent and fresh old sessions both fail after rename |
| applications.yml | 0 | Real HTTP old/new processes, values and committed cross-version orders |
| applications-rename.yml | 1 | Old HTTP reads fail; candidate reads the preserved name |
| applications-status-failure.yml | 1 | SQL passes, old domain model rejects processing after candidate commit |
| check-tightening.yml | 1 | NOT VALID CHECK rejects old zero-value write |
| index-drop.yml | 0 | Ordinary index creation and concurrent drop with catalog verification |

Build the worker before running. See docs/rollout.md for declarations and limits.
The reference compatible HTTP fixture has both name columns; it does not implement
a general expand/contract repair. unsupported/add_order_note.sql remains an ADD
COLUMN counterexample outside the rename/index/CHECK envelope.

## Controlled observations

- `contention.yml`: deliberately held writer, observed migration/probe wait, then release (0).
- `contention-timeout.yml`: held through the migration lock deadline (4).
- `benchmark.yml`: five sequential trial pairs and A/A controls; timing stays advisory.
- `plans.yml`: separate EXPLAIN ANALYZE before/after the index (0).

`fixtures/plan_orders.yml` is a deterministic selectivity fixture: two users and
6002 orders, with one order for user 7. The other order IDs are 102 and 1000–6999,
all owned by user 8. See [the protocol](../../docs/observations.md) for limits and
the distinction between compatibility, observations and advisory measurements.
