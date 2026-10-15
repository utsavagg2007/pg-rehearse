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
        return value
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError("Expected a nonempty relative file path without control characters")
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
        if type(value) is not int or value != 1:
            raise ValueError("schema_version must be integer 1")
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
    statement_ms: int = Field(default=5000, gt=0, le=600_000, strict=True)
    lock_ms: int = Field(default=1000, gt=0, le=600_000, strict=True)

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


class RunSpec(InputModel):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    postgres_image: str = Field(default="postgres:17", pattern=POSTGRES_IMAGE_PATTERN)
    schema_path: RelativePath
    fixtures_path: RelativePath | None = None
    contracts: ContractPaths
    migrations: list[MigrationStep] = Field(min_length=1, max_length=100)
    seed: int = Field(default=42, ge=0, le=2**32 - 1, strict=True)
    timeouts: Timeouts = Field(default_factory=Timeouts)

    @model_validator(mode="after")
    def unique_migration_ids(self) -> Self:
        ids = [step.id for step in self.migrations]
        if len(ids) != len(set(ids)):
            raise ValueError("Migration IDs must be unique")
        return self


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
