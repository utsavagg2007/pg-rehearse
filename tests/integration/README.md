# Integration test plan

Feature 1 has 13 real Docker/PostgreSQL cases in `test_runtime.py` and
`test_runtime_faults.py`. Prepare the official image with `docker pull postgres:17`,
start Docker, and run `uv run --locked pytest --run-docker`.

Step 2 adds four cases in `test_preflight.py`: accepted rename, ordinary index,
concurrent index, and CHECK shapes are preflighted before provisioning, then
checked against PostgreSQL 17 with fixed reviewed SQL. There are 17 real cases total.

Coverage includes readiness, PG17 identity, isolation settings, normal teardown,
SQL error, startup timeout, partial creation, lost create response, bookkeeping
failure, recovery, ownership mismatch, two concurrent lifetimes, cleanup failure,
SIGINT/SIGTERM, and SIGKILL. Fault injection surrounds real Docker resources; it
does not substitute a mocked database for PostgreSQL behavior.

Without the explicit option these cases skip. With it, a missing daemon or image
fails. Baseline seeding, contract execution, rename SQLSTATE `42703`, and the
additive control will get their own real tests as features 2–7 are implemented.
