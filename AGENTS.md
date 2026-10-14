# Project instructions

This repository is at the foundation stage. Read `PROGRESS.md` and
`IMPLEMENTATION_ORDER.md` before implementing the next feature.

Update `PROGRESS.md` after every implementation change with completed behavior,
checks actually run, pending work, and the next task. Keep `PROJECT_LAYOUT.md`
accurate when adding or moving modules.

Keep Docker operations in the host runtime, SQL execution in the worker pipeline,
and analysis independent of live database connections. Never turn placeholders or
missing evidence into a passing rehearsal. Preserve separate completion, verdict,
coverage, and cleanup fields.

Use the locked environment and run lint, formatting, type checks, and relevant
tests for substantive Python changes. Do not claim integration verification until
the feature has been exercised against real PostgreSQL. Retain ownership checks
for all resource cleanup; never remove unrelated Docker resources.
