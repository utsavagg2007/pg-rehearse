# End-to-end checks

Installed CLI rename/control rehearsals run against real PostgreSQL in
`tests/integration/test_rehearsal.py`. They check exits 1/0, candidate data,
SQLSTATE 42703, required coverage, final JSON/Markdown reports and cleanup.
Other tests cover invalid input before allocation (2), infrastructure/report/
cleanup failures (3), missing evidence and lock deadlines (4). Real tests require
`--run-docker` and a rebuilt worker image. Rollout and real HTTP application cases run in tests/integration/test_rollout.py.
