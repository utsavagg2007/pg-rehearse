# Architecture

## Product goal

Check whether a PostgreSQL migration preserves the behavior required by deployed
and candidate application versions, including rollout phases. A successful DDL
statement alone does not establish compatibility.

## Current implementation

The CLI can check its environment and load strict configuration and contract
models. It resolves input files below the configuration directory, rejects
duplicate YAML keys and IDs, and separates completion from verdict. The remaining
pipeline modules are placeholders with documented responsibilities.

## Target run lifecycle

```text
CLI -> validate inputs -> host coordinator -> owned Docker runtime
                                            |
                                  isolated database worker
                                            |
                  seed -> baseline probes -> migration -> rollout probes
                                            |
                         recorded evidence -> analysis -> reports
                                            |
                       coordinator cleanup -> final cleanup status
```

The coordinator alone has access to the Docker socket. Each run has a unique ID,
private network, ownership labels, and durable resource manifest. Cleanup checks
both manifest IDs and labels; it never prunes unrelated Docker resources.

The worker receives only resolved inputs and scoped database credentials, with no
Docker socket. Split setup, migration, workload, and observation privileges.
Apply statement and lock deadlines. Dispose of resources on success, failures,
interruptions, and readiness timeouts. Treat a cleanup failure as visible evidence.

Run baseline checks before applying a migration. A broken baseline is a setup
failure, not proof of migration incompatibility. Commit migration steps according
to their declared transaction mode. Reset failed transactions before continuing.

For independent experiments, clone immutable, verified templates. Rollout
experiments deliberately preserve sessions and committed mixed-version writes.
Rollback experiments run separately. Lock evidence and performance measurements
are advisory and must distinguish missing observations from passing observations.

## Evidence and results

`RunSpec` declares inputs and deadlines. `OperationResult` records version, phase,
SQLSTATE, and semantic assertions. `Finding` explains a decision with evidence.
`RunResult` keeps `completion`, `verdict`, `coverage`, and `cleanup` separate.

An incomplete experiment may confirm a failure, so `partial` + `fail` is valid.
A passing result requires all declared checks, complete execution, no blocking
findings, no failed operations/assertions, and successful cleanup. Checks need
phase-qualified IDs such as `baseline/deployed-v1/get-user` and
`post-migration/deployed-v1/get-user`. The future analysis layer must verify that
coverage IDs refer to actual evidence; the foundation models cannot authenticate
caller-supplied evidence.

Render terminal, JSON, Markdown, and eventually escaped HTML from the same result.
Persist reports after cleanup so cleanup status is accurate. Never include secrets
or connection credentials in reports or resource manifests.
