"""Configuration and evidence contracts shared across the future run pipeline."""

from __future__ import annotations

import math
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from pg_rehearse.errors import ExitCode


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


POSTGRES_IMAGE_PATTERN = r"^postgres:17(?:\.[0-9]+)?(?:-alpine)?(?:@sha256:[a-f0-9]{64})?$"


def relative_path(value: object) -> Path:
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError("Expected a nonempty relative file path without control characters")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("File paths must contain valid UTF-8 characters") from exc
    return Path(value)


def transaction_mode(value: object) -> TransactionMode:
    if isinstance(value, TransactionMode):
        return value
    if not isinstance(value, str):
        raise ValueError("Transaction mode must be transaction or autocommit")
    return TransactionMode(value)


RelativePath = Annotated[Path, BeforeValidator(relative_path)]
Scalar = StrictStr | StrictBool | StrictInt | StrictFloat | None


class InputModel(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("schema_version", mode="before", check_fields=False)
    @classmethod
    def exact_schema_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value

    @model_validator(mode="after")
    def finite_values(self) -> Self:
        def visit(value: object) -> None:
            if isinstance(value, str):
                if "\x00" in value:
                    raise ValueError("NUL characters are not supported")
                try:
                    value.encode("utf-8")
                except UnicodeError as exc:
                    raise ValueError("Strings must contain valid UTF-8 characters") from exc
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("NaN and infinity are not supported")
            if isinstance(value, dict):
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        for value in self.__dict__.values():
            visit(value)
        return self


class TransactionMode(StrEnum):
    TRANSACTION = "transaction"
    AUTOCOMMIT = "autocommit"


class Timeouts(InputModel):
    startup_seconds: int = Field(default=60, gt=0, le=600, strict=True)
    worker_seconds: int = Field(default=60, gt=0, le=3600, strict=True)
    statement_ms: int = Field(default=5000, gt=0, le=600_000, strict=True)
    lock_ms: int = Field(default=1000, gt=0, le=600_000, strict=True)
    application_ms: int = Field(default=5000, gt=0, le=600_000, strict=True)

    @model_validator(mode="after")
    def coherent_deadlines(self) -> Self:
        if self.lock_ms > self.statement_ms:
            raise ValueError("lock_ms must not exceed statement_ms")
        return self


class MigrationStep(InputModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    path: RelativePath
    transaction: Annotated[TransactionMode, BeforeValidator(transaction_mode)] = (
        TransactionMode.TRANSACTION
    )


class ContractPaths(InputModel):
    deployed: RelativePath
    candidate: RelativePath | None = None


class SemanticAssertions(InputModel):
    columns: list[str] | None = None
    rows: list[list[Scalar]] | None = Field(default=None, max_length=10_000)
    row_count: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def consistent_expectations(self) -> Self:
        if self.columns is None and self.rows is None and self.row_count is None:
            raise ValueError("At least one result assertion is required")
        if self.rows is not None:
            if self.row_count is not None and len(self.rows) != self.row_count:
                raise ValueError("rows and row_count disagree")
            if self.columns is not None and any(len(row) != len(self.columns) for row in self.rows):
                raise ValueError("Each expected row must match the expected columns")
        return self


class OperationSpec(InputModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    sql: str = Field(min_length=1)
    parameters: list[Scalar] | dict[str, Scalar] = Field(default_factory=list)
    required: bool = True
    expect: SemanticAssertions


class ContractSpec(InputModel):
    schema_version: Literal[1] = 1
    version: str = Field(min_length=1, max_length=200, pattern=r"\S")
    operations: list[OperationSpec] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_operation_ids(self) -> Self:
        ids = [operation.id for operation in self.operations]
        if len(ids) != len(set(ids)):
            raise ValueError("Operation IDs must be unique within a contract")
        return self


class RolloutOperation(OperationSpec):
    actor: Literal["deployed", "candidate"]


class RolloutPhase(InputModel):
    id: Literal["mixed_versions", "candidate_only", "app_rollback"]
    operations: list[RolloutOperation] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_operations(self) -> Self:
        ids = [op.id for op in self.operations]
        if len(ids) != len(set(ids)):
            raise ValueError("Rollout operation IDs must be unique within a phase")
        if any(not op.required for op in self.operations):
            raise ValueError("Declared rollout operations must be required")
        return self


class RolloutSpec(InputModel):
    persistent_old_sessions: int = Field(default=1, ge=1, le=4)
    phases: list[RolloutPhase] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def schema_first_order(self) -> Self:
        if [phase.id for phase in self.phases] != [
            "mixed_versions",
            "candidate_only",
            "app_rollback",
        ]:
            raise ValueError("Rollout phases must be mixed_versions, candidate_only, app_rollback")
        return self


class ApplicationsSpec(InputModel):
    adapter: Literal["orders"]
    user_id: int = Field(gt=0)
    expected_name: str = Field(min_length=1, max_length=1000)
    order_id_base: int = Field(default=9000, gt=0, lt=2**63 - 3)
    candidate_status: Literal["pending", "processing"] = "pending"


class ContentionSpec(InputModel):
    blocker: OperationSpec
    probe: OperationSpec
    poll_ms: int = Field(default=50, ge=10, le=1000)
    observe_ms: int = Field(default=400, ge=50, le=10_000)
    release: Literal["after_observation", "migration_timeout"] = "after_observation"


class BenchmarkSpec(InputModel):
    operations: list[str] = Field(min_length=1, max_length=5)
    trials: int = Field(default=5, ge=1, le=5)
    warmups: int = Field(default=50, ge=0, le=100)
    samples: int = Field(default=200, ge=1, le=1000)
    absolute_ms: float = Field(default=5.0, gt=0)
    ratio: float = Field(default=1.20, gt=1)


class PlansSpec(InputModel):
    operations: list[str] = Field(min_length=1, max_length=5)
    analyze: bool = False


class RunSpec(InputModel):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    postgres_image: str = Field(default="postgres:17", pattern=POSTGRES_IMAGE_PATTERN)
    schema_path: RelativePath
    fixtures_path: RelativePath | None = None
    contracts: ContractPaths
    migrations: list[MigrationStep] = Field(min_length=1, max_length=100)
    seed: int = Field(default=42, ge=0, le=2**32 - 1, strict=True)
    rollout: RolloutSpec | None = None
    applications: ApplicationsSpec | None = None
    contention: ContentionSpec | None = None
    benchmark: BenchmarkSpec | None = None
    plans: PlansSpec | None = None
    timeouts: Timeouts = Field(default_factory=Timeouts)

    @model_validator(mode="after")
    def unique_migration_ids(self) -> Self:
        ids = [step.id for step in self.migrations]
        if len(ids) != len(set(ids)):
            raise ValueError("Migration IDs must be unique")
        if self.rollout and not self.contracts.candidate:
            raise ValueError("Rollout requires a candidate contract")
        if self.applications and not self.rollout:
            raise ValueError("Application probes require declared rollout phases")
        if self.contention and not (
            self.contention.poll_ms <= self.contention.observe_ms < self.timeouts.lock_ms
        ):
            raise ValueError("Contention requires poll_ms <= observe_ms < lock_ms")
        return self


class FixtureSpec(InputModel):
    schema_version: Literal[1] = 1
    tables: dict[str, list[dict[str, Scalar]]]

    @model_validator(mode="after")
    def bounded_rows(self) -> Self:
        if sum(len(rows) for rows in self.tables.values()) > 10_000:
            raise ValueError("At most 10000 explicit fixture rows are supported")
        return self


class Completion(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class CleanupStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class AssertionResult(StrictModel):
    name: str
    passed: bool = Field(strict=True)
    expected: Any = None
    actual: Any = None


class OperationResult(StrictModel):
    operation_id: str
    version: str
    phase: str
    success: bool = Field(strict=True)
    sqlstate: str | None = Field(default=None, pattern=r"^[0-9A-Z]{5}$")
    error: str | None = None
    error_kind: (
        Literal[
            "sql_error",
            "assertion_error",
            "result_limit",
            "unsupported_result",
            "operation_deadline",
            "connection_error",
        ]
        | None
    ) = None
    assertions: list[AssertionResult] = Field(default_factory=list)
    actor: str | None = None
    backend_pid: int | None = Field(default=None, gt=0, strict=True)
    committed: bool = Field(default=False, strict=True)


class BaselineEvidence(InputModel):
    success: bool
    seed: int
    schema_statements: int = Field(ge=0)
    table_rows: dict[str, int] = Field(default_factory=dict)
    data_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    error_kind: Literal["schema_error", "fixture_error", "verification_error"] | None = None
    sqlstate: str | None = Field(default=None, pattern=r"^[0-9A-Z]{5}$")


class Finding(StrictModel):
    rule_id: str
    severity: Severity
    explanation: str
    operation_id: str | None = None
    phase: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class IndexFact(InputModel):
    name: str
    table: str
    valid: bool
    ready: bool
    method: str
    unique: bool
    columns: list[str]
    options: list[int]
    definition: str = Field(min_length=1)


class CheckFact(InputModel):
    name: str
    table: str
    validated: bool
    definition: str = Field(min_length=1)


class CatalogState(InputModel):
    columns: dict[str, list[str]]
    indexes: list[IndexFact]
    checks: list[CheckFact]


class PhaseResult(InputModel):
    completion: Literal["complete", "partial"]
    id: str
    checks: list[str]
    barrier: Literal["baseline_verified", "migration_committed", "committed_writes"]


class ApplicationResult(InputModel):
    probe_id: str
    phase: str
    version: Literal["deployed", "candidate"]
    actor: str
    revision: str
    process_id: int | None = Field(default=None, gt=0)
    backend_pid: int | None = Field(default=None, gt=0, strict=True)
    exit_code: int | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    success: bool
    error_kind: (
        Literal[
            "sql_error",
            "domain_error",
            "assertion_error",
            "process_error",
            "application_deadline",
            "invalid_response",
            "connection_error",
        ]
        | None
    ) = None
    sqlstate: str | None = Field(default=None, pattern=r"^[0-9A-Z]{5}$")
    assertions: list[AssertionResult] = Field(default_factory=list)


class MigrationResult(InputModel):
    step_id: str
    phase: str
    transaction: Annotated[TransactionMode, BeforeValidator(transaction_mode)]
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    statements: int = Field(ge=1)
    executed: int = Field(ge=0)
    committed: bool
    sqlstate: str | None = Field(default=None, pattern=r"^[0-9A-Z]{5}$")
    error_kind: Literal["sql_error", "migration_deadline", "connection_error"] | None = None
    catalog_before: CatalogState | None = None
    catalog_after: CatalogState | None = None


class TemplateEvidence(InputModel):
    database: Literal["rehearsal"] = "rehearsal"
    identity: str = Field(pattern=r"^[a-f0-9]{64}$")
    data_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sealed: bool


class BranchEvidence(InputModel):
    database: str
    phase: str
    data_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ActivitySample(InputModel):
    pid: int = Field(gt=0)
    application_name: str
    state: str | None
    wait_event_type: str | None
    wait_event: str | None
    blockers: list[int]


class LockFact(InputModel):
    pid: int = Field(gt=0)
    locktype: str
    mode: str
    granted: bool
    waitstart: str | None
    relation: int | None
    transactionid: str | None


class LockSample(InputModel):
    elapsed_ms: float = Field(ge=0)
    observed_at: str
    overhead_ms: float = Field(ge=0)
    activity: list[ActivitySample]
    locks: list[LockFact]


class ClientEvent(InputModel):
    name: str
    elapsed_ms: float = Field(ge=0)


class ContentionResult(InputModel):
    actor_pids: dict[str, int]
    events: list[ClientEvent] = Field(default_factory=list)
    samples: list[LockSample] = Field(default_factory=list, max_length=1000)
    missed_polls: int = Field(default=0, ge=0)
    observer_error: Literal["database_error"] | None = None
    blocker: OperationResult | None = None
    probe: OperationResult | None = None
    blocker_released: bool = False
    hold_ms: float = Field(default=0, ge=0)
    poll_ms: int = Field(gt=0)


class TimingSample(InputModel):
    operation_id: str
    iteration: int = Field(ge=0)
    warmup: bool
    elapsed_ms: float = Field(ge=0)
    success: bool
    error_kind: (
        Literal[
            "sql_error",
            "assertion_error",
            "result_limit",
            "unsupported_result",
            "operation_deadline",
            "connection_error",
        ]
        | None
    ) = None
    sqlstate: str | None = Field(default=None, pattern=r"^[0-9A-Z]{5}$")


class BenchmarkEvidence(InputModel):
    samples: list[TimingSample] = Field(default_factory=list, max_length=5500)
    environment: dict[str, Scalar]
    schedule_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PlanEvidence(InputModel):
    operation_id: str
    analyze: bool
    success: bool
    committed: bool = False
    raw: dict[str, Any] | None = Field(default=None, repr=False)
    error_kind: Literal["sql_error", "plan_limit", "invalid_plan"] | None = None
    sqlstate: str | None = Field(default=None, pattern=r"^[0-9A-Z]{5}$")
    settings: dict[str, Scalar]


class Coverage(StrictModel):
    required: list[str] = Field(default_factory=list)
    completed: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_checks(self) -> Self:
        if len(self.required) != len(set(self.required)):
            raise ValueError("Required coverage IDs must be unique")
        if len(self.completed) != len(set(self.completed)):
            raise ValueError("Completed coverage IDs must be unique")
        return self

    @property
    def missing(self) -> list[str]:
        return sorted(set(self.required) - set(self.completed))


class RunResult(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    completion: Completion = Completion.PARTIAL
    verdict: Verdict = Verdict.INCONCLUSIVE
    coverage: Coverage = Field(default_factory=Coverage)
    operations: list[OperationResult] = Field(default_factory=list)
    baseline: BaselineEvidence | None = None
    migrations: list[MigrationResult] = Field(default_factory=list)
    template: TemplateEvidence | None = None
    branches: list[BranchEvidence] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    phases: list[PhaseResult] = Field(default_factory=list)
    applications: list[ApplicationResult] = Field(default_factory=list)
    evidence_levels: list[str] = Field(default_factory=lambda: ["sql_contract"])
    contention: ContentionResult | None = None
    benchmarks: list[dict[str, Any]] = Field(default_factory=list)
    performance: list[dict[str, Any]] = Field(default_factory=list)
    plans: list[dict[str, Any]] = Field(default_factory=list)
    environment: dict[str, Scalar] = Field(default_factory=dict)
    cleanup: CleanupStatus = CleanupStatus.PENDING

    @model_validator(mode="after")
    def require_evidence_for_pass(self) -> Self:
        if self.verdict != Verdict.PASS:
            return self
        if self.completion != Completion.COMPLETE:
            raise ValueError("A passing verdict requires a complete run")
        if not self.coverage.required or self.coverage.missing:
            raise ValueError("A passing verdict requires every required check")
        if self.cleanup not in (CleanupStatus.COMPLETE, CleanupStatus.NOT_REQUIRED):
            raise ValueError("A passing verdict requires successful cleanup")
        if any(finding.severity == Severity.ERROR for finding in self.findings):
            raise ValueError("A passing verdict cannot contain blocking findings")
        if any(
            not operation.success or any(not item.passed for item in operation.assertions)
            for operation in self.operations
        ):
            raise ValueError("A passing verdict cannot contain failed operations or assertions")
        if any(
            not app.success or any(not a.passed for a in app.assertions)
            for app in self.applications
        ):
            raise ValueError("A passing verdict cannot contain failed application probes")
        if self.contention and (
            not self.contention.blocker_released
            or not self.contention.samples
            or not self.contention.blocker
            or not self.contention.blocker.success
            or not self.contention.probe
            or not self.contention.probe.success
        ):
            raise ValueError("A passing verdict requires observed, released contention actors")
        return self

    @property
    def exit_code(self) -> ExitCode:
        if self.verdict == Verdict.FAIL:
            return ExitCode.COMPATIBILITY_FAILURE
        if (
            self.completion == Completion.INFRASTRUCTURE_ERROR
            or self.cleanup == CleanupStatus.FAILED
        ):
            return ExitCode.INFRASTRUCTURE_ERROR
        if self.verdict == Verdict.PASS:
            return ExitCode.SUCCESS
        return ExitCode.INCONCLUSIVE
