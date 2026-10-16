# End-to-end checks

`test_evaluation.py` runs all seven fixed labels through the real pipeline and
compares their actual exits, completion, verdict, coverage, rule/SQLSTATE and
cleanup. Saved JSON must match the returned result; report formats must exist;
owned resource IDs must be absent afterward. Unsupported SQL must create no run
directory. These are seven Docker-enabled cases, with six actual rehearsals and
one preflight refusal. The standalone `scripts/evaluate.py` retains the same matrix
and summaries for CI/release checks. See `evaluation/README.md`.

Installed CLI rename/control rehearsals run against real PostgreSQL in
`tests/integration/test_rehearsal.py`. They check exits 1/0, candidate data,
SQLSTATE 42703, required coverage, final JSON/Markdown reports and cleanup.
Other tests cover invalid input before allocation (2), infrastructure/report/
cleanup failures (3), missing evidence and lock deadlines (4). Real tests require
`--run-docker` and a rebuilt worker image. Rollout and real HTTP application cases run in tests/integration/test_rollout.py.
