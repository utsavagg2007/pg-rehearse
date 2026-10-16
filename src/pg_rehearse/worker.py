"""SQL execution boundary inside the private run network; never talks to Docker."""

import math
import sys
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from pg_rehearse.config import load_worker_config
from pg_rehearse.errors import ExitCode, WorkerDeadline
from pg_rehearse.fixtures.seed import seed_baseline, verify_baseline
from pg_rehearse.migration.executor import execute_migrations
from pg_rehearse.runtime.roles import ROLE_NAMES, Role
from pg_rehearse.worker_protocol import (
    MAX_REQUEST_BYTES,
    RoleEvidence,
    WorkerEvidence,
    WorkerFailure,
    WorkerRequest,
)
from pg_rehearse.workload.contracts import contract_coverage
from pg_rehearse.workload.runner import execution_deadline, run_contract


@contextmanager
def connect_as(
    request: WorkerRequest, role: Role, *, actor: str | None = None
) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """Future pipeline stages use this scoped connection, never a bootstrap connection."""
    options = (
        f"-c statement_timeout={request.timeouts.statement_ms} "
        f"-c lock_timeout={request.timeouts.lock_ms} "
        f"-c idle_in_transaction_session_timeout={request.timeouts.statement_ms} "
        "-c search_path=public,pg_catalog"
    )
    with psycopg.connect(
        host=request.database_host,
        port=5432,
        dbname=request.database,
        user=ROLE_NAMES[role],
        password=request.credentials[role].get_secret_value(),
        connect_timeout=max(2, min(5, math.ceil(request.timeouts.worker_seconds))),
        application_name=(
            f"pgr/{request.run_id[:12]}/{request.task}/{actor}"
            if actor
            else f"pg-rehearse/{request.run_id}/{role}"
        ),
        options=options,
        sslmode="disable",
        passfile="/dev/null",
        autocommit=True,
    ) as connection:
        if role == "setup":
            connection.execute("SET ROLE rehearse_migration")
        yield connection


def check_roles(request: WorkerRequest) -> WorkerEvidence:
    """Execute real identity/permission probes; this is not application compatibility evidence."""
    roles = []
    for role in ROLE_NAMES:
        with connect_as(request, role) as connection:
            row = connection.execute("""
                SELECT session_user, current_user,
                    current_setting('server_version_num')::int / 10000,
                    (SELECT setting::int FROM pg_settings WHERE name = 'statement_timeout'),
                    (SELECT setting::int FROM pg_settings WHERE name = 'lock_timeout'),
                    (SELECT rolsuper OR rolcreatedb OR rolcreaterole
                            OR rolreplication OR rolbypassrls
                     FROM pg_roles WHERE rolname = session_user),
                    has_schema_privilege(current_user, 'public', 'CREATE'),
                    has_database_privilege(current_user, current_database(), 'CREATE'),
                    has_database_privilege(current_user, current_database(), 'TEMP'),
                    pg_has_role(current_user, 'pg_read_all_stats', 'USAGE')
            """).fetchone()
            if row is None:
                raise ValueError("Missing role probe")
            roles.append(
                RoleEvidence.model_validate(
                    dict(
                        zip(
                            (
                                "session_user",
                                "current_user",
                                "server_major",
                                "statement_ms",
                                "lock_ms",
                                "elevated",
                                "schema_create",
                                "database_create",
                                "database_temp",
                                "read_all_stats",
                            ),
                            row,
                            strict=True,
                        )
                    )
                    | {"role": role}
                )
            )
    evidence = WorkerEvidence(
        run_id=request.run_id,
        completion="complete",
        input_hashes=request.inputs.hashes,
        roles=roles,
        task=request.task,
        database=request.database,
        trial=request.trial,
        arm=request.arm,
    )
    evidence.verify_roles(request)
    return evidence


def execute_baseline(request: WorkerRequest) -> WorkerEvidence:
    loaded = load_worker_config(request.inputs)
    evidence = check_roles(request)
    with connect_as(request, "setup") as connection:
        loader = seed_baseline if request.task in {"baseline", "seed"} else verify_baseline
        evidence.baseline = loader(connection, loaded.schema_sql, loaded.fixtures, loaded.spec.seed)
    if request.task in {"contention", "benchmark", "plan_baseline", "plan_candidate"}:
        from pg_rehearse.observe.runner import execute_diagnostics

        if evidence.baseline.success:
            execute_diagnostics(request, loaded, evidence)
        else:
            evidence.completion = "partial"
        evidence.verify(request)
        return evidence
    if request.task in {"rollout", "rollback"}:
        from pg_rehearse.rollout.runner import execute_rollout
        from pg_rehearse.rollout.validation import rollout_coverage

        if evidence.baseline.success:
            execute_rollout(request, loaded, evidence)
        else:
            evidence.coverage = rollout_coverage(loaded, evidence)
            evidence.completion = "partial"
        evidence.verify(request)
        return evidence
    contract = (
        loaded.candidate_contract if request.task == "post_candidate" else loaded.deployed_contract
    )
    if contract is None:
        raise ValueError("Missing experiment contract")
    phase = "baseline" if request.task in {"baseline", "baseline_probe"} else request.task
    ready = evidence.baseline.success
    if ready and request.task in {"post_deployed", "post_candidate"}:
        with connect_as(request, "migration") as connection:
            evidence.migrations = execute_migrations(connection, loaded, phase=phase)
        ready = len(evidence.migrations) == len(loaded.spec.migrations) and all(
            result.committed for result in evidence.migrations
        )
    if ready and request.task != "seed":
        with connect_as(request, "workload") as connection:
            evidence.operations = run_contract(
                connection, contract, phase=phase, statement_ms=request.timeouts.statement_ms
            )
    evidence.coverage = (
        contract_coverage(contract, phase, evidence.operations)
        if request.task != "seed"
        else evidence.coverage
    )
    evidence.completion = (
        "complete"
        if ready
        and (request.task == "seed" or len(evidence.operations) == len(contract.operations))
        else "partial"
    )
    evidence.verify(request)
    return evidence


def main() -> int:
    request = None
    try:
        with execution_deadline(10):
            payload = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
        if len(payload) > MAX_REQUEST_BYTES or not payload.endswith(b"\n"):
            raise ValueError("Invalid worker input envelope")
        request = WorkerRequest.model_validate_json(payload)
        with execution_deadline(request.timeouts.worker_seconds):
            evidence = execute_baseline(request)
        print(evidence.model_dump_json())
        return ExitCode.SUCCESS
    except WorkerDeadline:
        failure = WorkerFailure(error="worker_deadline")
    except psycopg.Error as exc:
        failure = WorkerFailure(error="database_error", sqlstate=exc.sqlstate)
    except Exception:
        # Validation and libpq messages can echo passwords or input data.
        failure = WorkerFailure(error="internal_error" if request else "invalid_request")
    failure.run_id = request.run_id if request else None
    print(failure.model_dump_json())
    return ExitCode.INFRASTRUCTURE_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
