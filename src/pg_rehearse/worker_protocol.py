"""Versioned, bounded worker input and evidence; no Docker or live database dependency."""

import hashlib
import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal, Self, get_args

from pydantic import Field, SecretStr, model_validator

from pg_rehearse.models import (
    ApplicationResult,
    BaselineEvidence,
    BenchmarkEvidence,
    ContentionResult,
    Coverage,
    InputModel,
    MigrationResult,
    OperationResult,
    PhaseResult,
    PlanEvidence,
    TemplateEvidence,
    Timeouts,
)
from pg_rehearse.runtime.roles import ROLE_NAMES, Role

if TYPE_CHECKING:
    from pg_rehearse.config import LoadedConfig

MAX_INPUT_TOTAL = 8 * 1_048_576
MAX_REQUEST_BYTES = 6 * MAX_INPUT_TOTAL + 65_536
MAX_RESPONSE_BYTES = 8 * 1_048_576
WORKER_IMAGE = "pg-rehearse-worker:0.1.0"
WorkerTask = Literal[
    "baseline",
    "seed",
    "baseline_probe",
    "post_deployed",
    "post_candidate",
    "rollout",
    "rollback",
    "contention",
    "benchmark",
    "plan_baseline",
    "plan_candidate",
]
BenchmarkArm = Literal["baseline", "candidate", "control_a", "control_b"]


def experiment_id(
    task: WorkerTask, trial: int | None = None, arm: BenchmarkArm | None = None
) -> str:
    if task not in get_args(WorkerTask):
        raise ValueError("Unknown experiment task")
    if task == "benchmark":
        if (
            type(trial) is not int
            or not 1 <= trial <= 5
            or arm not in {"baseline", "candidate", "control_a", "control_b"}
        ):
            raise ValueError("Benchmark requires a bounded trial and arm")
        return f"benchmark_{trial}_{arm}"
    if trial is not None or arm is not None:
        raise ValueError("Only benchmark tasks accept a trial and arm")
    return task


def experiment_tasks(
    loaded: "LoadedConfig",
) -> list[tuple[WorkerTask, int | None, BenchmarkArm | None]]:
    tasks: list[tuple[WorkerTask, int | None, BenchmarkArm | None]] = [
        ("baseline_probe", None, None),
        ("post_deployed", None, None),
    ]
    if loaded.candidate_contract:
        tasks.append(("post_candidate", None, None))
    if loaded.spec.rollout:
        tasks.extend([("rollout", None, None), ("rollback", None, None)])
    if loaded.spec.contention:
        tasks.append(("contention", None, None))
    if loaded.spec.benchmark:
        for trial in range(1, loaded.spec.benchmark.trials + 1):
            arms: list[BenchmarkArm] = ["control_a", "control_b", "baseline", "candidate"]
            for arm in arms if trial % 2 else reversed(arms):
                tasks.append(("benchmark", trial, arm))
    if loaded.spec.plans:
        tasks.extend([("plan_baseline", None, None), ("plan_candidate", None, None)])
    return tasks


def task_database(
    run_id: str, task: WorkerTask, trial: int | None = None, arm: BenchmarkArm | None = None
) -> str:
    name = experiment_id(task, trial, arm)
    if task in {"baseline", "seed"}:
        return "rehearsal"
    return f"pgr_{run_id}_{name}"


class InputFile(InputModel):
    name: str = Field(min_length=1, max_length=4096)
    text: str = Field(repr=False)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def verify_snapshot(self) -> Self:
        path = PurePosixPath(self.name)
        if path.is_absolute() or ".." in path.parts or "\\" in self.name:
            raise ValueError("Worker inputs must use contained relative names")
        if hashlib.sha256(self.text.encode()).hexdigest() != self.sha256:
            raise ValueError("Worker input hash mismatch")
        return self


class WorkerInputs(InputModel):
    files: list[InputFile] = Field(min_length=1, max_length=105)

    @model_validator(mode="after")
    def bounded_inputs(self) -> Self:
        if sum(len(file.text.encode()) for file in self.files) > MAX_INPUT_TOTAL:
            raise ValueError("Accepted inputs exceed 8 MiB total")
        return self

    @property
    def hashes(self) -> list[str]:
        return [file.sha256 for file in self.files]


class WorkerRequest(InputModel):
    schema_version: Literal[1] = 1
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    database_host: str = Field(pattern=r"^pgr-[a-f0-9]{32}-postgres$")
    credentials: dict[Role, SecretStr]
    inputs: WorkerInputs
    timeouts: Timeouts
    task: WorkerTask = "baseline"
    database: str = "rehearsal"
    trial: int | None = Field(default=None, ge=1, le=5)
    arm: BenchmarkArm | None = None

    @model_validator(mode="after")
    def complete_credentials(self) -> Self:
        if set(self.credentials) != set(ROLE_NAMES):
            raise ValueError("Exactly four scoped credentials are required")
        if self.database_host != f"pgr-{self.run_id}-postgres":
            raise ValueError("Database host does not match the run")
        if self.database != task_database(self.run_id, self.task, self.trial, self.arm):
            raise ValueError("Database does not match the run experiment")
        if any(not secret.get_secret_value() for secret in self.credentials.values()):
            raise ValueError("Empty credentials are not allowed")
        return self

    def to_wire(self) -> bytes:
        payload = self.model_dump(mode="json")
        payload["credentials"] = {
            role: secret.get_secret_value() for role, secret in self.credentials.items()
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"


class RoleEvidence(InputModel):
    role: Role
    session_user: str
    current_user: str
    server_major: int
    statement_ms: int
    lock_ms: int
    elevated: bool
    schema_create: bool
    database_create: bool
    database_temp: bool
    read_all_stats: bool


class WorkerEvidence(InputModel):
    schema_version: Literal[2] = 2
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    completion: Literal["complete", "partial"]
    input_hashes: list[str]
    roles: list[RoleEvidence]
    baseline: BaselineEvidence | None = None
    operations: list[OperationResult] = Field(default_factory=list, max_length=12000)
    phases: list[PhaseResult] = Field(default_factory=list)
    applications: list[ApplicationResult] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    task: WorkerTask = "baseline"
    database: str = "rehearsal"
    trial: int | None = Field(default=None, ge=1, le=5)
    arm: BenchmarkArm | None = None
    migrations: list[MigrationResult] = Field(default_factory=list, max_length=100)
    contention: ContentionResult | None = None
    benchmark: BenchmarkEvidence | None = None
    plans: list[PlanEvidence] = Field(default_factory=list, max_length=5)

    def verify_roles(self, request: WorkerRequest) -> None:
        if self.run_id != request.run_id or self.input_hashes != request.inputs.hashes:
            raise ValueError("Worker evidence does not match the accepted run inputs")
        if sorted(item.role for item in self.roles) != sorted(ROLE_NAMES):
            raise ValueError("Missing or duplicate role evidence")
        for item in self.roles:
            effective = "migration" if item.role == "setup" else item.role
            if (
                item.session_user != ROLE_NAMES[item.role]
                or item.current_user != ROLE_NAMES[effective]
                or item.server_major != 17
                or item.statement_ms != request.timeouts.statement_ms
                or item.lock_ms != request.timeouts.lock_ms
                or item.elevated
                or item.database_create
                or item.database_temp
                or item.schema_create != (item.role in {"setup", "migration"})
                or item.read_all_stats != (item.role == "observer")
            ):
                raise ValueError("Worker role evidence violates the execution boundary")

    def verify(self, request: WorkerRequest) -> None:
        from pg_rehearse.config import load_worker_config
        from pg_rehearse.workload.contracts import contract_coverage, verify_operation

        self.verify_roles(request)
        loaded = load_worker_config(request.inputs)
        if (self.task, self.database, self.trial, self.arm) != (
            request.task,
            request.database,
            request.trial,
            request.arm,
        ):
            raise ValueError("Wrong experiment identity")
        diagnostic = request.task in {"contention", "benchmark", "plan_baseline", "plan_candidate"}
        if not diagnostic and (self.contention or self.benchmark or self.plans):
            raise ValueError("Unexpected diagnostic evidence")
        baseline = self.baseline
        if baseline is None or baseline.seed != loaded.spec.seed:
            raise ValueError("Missing or mismatched baseline evidence")
        contract = (
            loaded.candidate_contract
            if request.task == "post_candidate"
            else loaded.deployed_contract
        )
        if contract is None:
            raise ValueError("Missing experiment contract")
        phase = "baseline" if request.task in {"baseline", "baseline_probe"} else request.task
        if (
            not diagnostic
            and request.task not in {"rollout", "rollback"}
            and self.coverage
            != (
                Coverage()
                if request.task == "seed"
                else contract_coverage(contract, phase, self.operations)
            )
        ):
            raise ValueError("Contract coverage does not match recorded operations")
        if not baseline.success:
            if (
                self.completion != "partial"
                or not baseline.error_kind
                or self.operations
                or self.migrations
                or self.phases
                or self.applications
                or self.contention
                or self.benchmark
                or self.plans
                or baseline.data_sha256
                or baseline.table_rows
                or baseline.schema_statements
            ):
                raise ValueError("Failed setup cannot claim completed probes")
            return
        expected_counts = {
            stmt.node["relation"]["relname"]: 0 for stmt in loaded.schema_sql.statements
        }
        if loaded.fixtures:
            expected_counts.update(
                {name: len(rows) for name, rows in loaded.fixtures.tables.items()}
            )
        if (
            baseline.error_kind
            or baseline.sqlstate
            or not baseline.data_sha256
            or baseline.schema_statements != len(loaded.schema_sql.statements)
            or baseline.table_rows != expected_counts
        ):
            raise ValueError("Incomplete baseline setup evidence")
        if request.task == "seed":
            if (
                self.operations
                or self.migrations
                or self.phases
                or self.applications
                or self.completion != "complete"
            ):
                raise ValueError("Seed task cannot claim application or migration evidence")
            return
        if diagnostic:
            from pg_rehearse.observe.validation import verify_diagnostics

            verify_diagnostics(loaded, request, self)
            return
        if request.task in {"rollout", "rollback"}:
            from pg_rehearse.rollout.validation import verify_rollout

            verify_rollout(loaded, request, self)
            return
        if self.phases or self.applications:
            raise ValueError("Unexpected rollout or application evidence")
        migrating = request.task in {"post_deployed", "post_candidate"}
        if not migrating and self.migrations:
            raise ValueError("Baseline task cannot execute migrations")
        if migrating and not verify_migrations(loaded, self.migrations, phase):
            if self.operations or self.completion != "partial":
                raise ValueError("Uncommitted migrations cannot claim probes or completion")
            return
        if len(self.operations) > len(contract.operations):
            raise ValueError("Unexpected contract operations")
        for expected, result in zip(contract.operations, self.operations, strict=False):
            if (result.operation_id, result.version, result.phase) != (
                expected.id,
                contract.version,
                phase,
            ) or result.error is not None:
                raise ValueError("Wrong operation identity or unsafe error text")
            if result.actor is not None or result.backend_pid is not None or result.committed:
                raise ValueError("Unexpected rollout session or commit evidence")
            verify_operation(expected, result)
        complete = len(self.operations) == len(contract.operations)
        if (self.completion == "complete") != complete:
            raise ValueError("Missing operation evidence cannot complete the worker")


def verify_migrations(loaded: "LoadedConfig", results: list[MigrationResult], phase: str) -> bool:
    if len(results) > len(loaded.spec.migrations):
        raise ValueError("Unexpected migration evidence")
    failed = False
    for step, document, migration_result in zip(
        loaded.spec.migrations, loaded.migration_sql, results, strict=False
    ):
        if failed or (
            migration_result.step_id,
            migration_result.phase,
            migration_result.transaction,
            migration_result.source_sha256,
            migration_result.statements,
        ) != (step.id, phase, step.transaction, document.sha256, len(document.statements)):
            raise ValueError("Wrong migration identity or ordering")
        if (
            migration_result.executed > migration_result.statements
            or (not migration_result.committed and migration_result.error_kind is None)
            or migration_result.committed
            != (
                migration_result.error_kind is None
                and migration_result.executed == migration_result.statements
                and migration_result.sqlstate is None
            )
        ):
            raise ValueError("Inconsistent migration commit evidence")
        failed = not migration_result.committed
    return not failed and len(results) == len(loaded.spec.migrations)


class RehearsalEvidence(InputModel):
    seed: WorkerEvidence | None = None
    template: TemplateEvidence | None = None
    experiments: list[WorkerEvidence] = Field(default_factory=list)


class WorkerFailure(InputModel):
    schema_version: Literal[1] = 1
    run_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    error: Literal["worker_deadline", "database_error", "invalid_request", "internal_error"]
    sqlstate: str | None = Field(default=None, pattern=r"^[0-9A-Z]{5}$")
