"""Configuration and evidence contracts shared across the future run pipeline."""

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pg_rehearse.errors import ExitCode


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TransactionMode(StrEnum):
    TRANSACTION = "transaction"
    AUTOCOMMIT = "autocommit"


class Timeouts(StrictModel):
    startup_seconds: int = Field(default=60, gt=0, le=600, strict=True)
    statement_ms: int = Field(default=5000, gt=0, le=600_000, strict=True)
    lock_ms: int = Field(default=1000, gt=0, le=600_000, strict=True)


class MigrationStep(StrictModel):
    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    path: Path
    transaction: TransactionMode = TransactionMode.TRANSACTION


class ContractPaths(StrictModel):
    deployed: Path
    candidate: Path | None = None


class RunSpec(StrictModel):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    postgres_image: str = "postgres:17"
    schema_path: Path
    fixtures_path: Path | None = None
    contracts: ContractPaths
    migrations: list[MigrationStep] = Field(min_length=1)
    seed: int = Field(default=42, ge=0, strict=True)
    timeouts: Timeouts = Field(default_factory=Timeouts)

    @model_validator(mode="after")
    def unique_migration_ids(self) -> Self:
        ids = [step.id for step in self.migrations]
        if len(ids) != len(set(ids)):
            raise ValueError("Migration IDs must be unique")
        return self


class SemanticAssertions(StrictModel):
    columns: list[str] | None = None
    rows: list[list[Any]] | None = None
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


class OperationSpec(StrictModel):
    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    sql: str = Field(min_length=1)
    parameters: list[Any] = Field(default_factory=list)
    required: bool = True
    expect: SemanticAssertions


class ContractSpec(StrictModel):
    schema_version: Literal[1] = 1
    version: str = Field(min_length=1)
    operations: list[OperationSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_operation_ids(self) -> Self:
        ids = [operation.id for operation in self.operations]
        if len(ids) != len(set(ids)):
            raise ValueError("Operation IDs must be unique within a contract")
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
    passed: bool
    expected: Any = None
    actual: Any = None


class OperationResult(StrictModel):
    operation_id: str
    version: str
    phase: str
    success: bool
    sqlstate: str | None = Field(default=None, pattern=r"^[0-9A-Z]{5}$")
    error: str | None = None
    assertions: list[AssertionResult] = Field(default_factory=list)


class Finding(StrictModel):
    rule_id: str
    severity: Severity
    explanation: str
    operation_id: str | None = None
    phase: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


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
    findings: list[Finding] = Field(default_factory=list)
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
