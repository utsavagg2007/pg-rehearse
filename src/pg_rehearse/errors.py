"""User-facing failures with explicit CLI exit codes."""

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    COMPATIBILITY_FAILURE = 1
    INVALID_INPUT = 2
    INFRASTRUCTURE_ERROR = 3
    INCONCLUSIVE = 4


class ConfigurationError(ValueError):
    """Configuration cannot be used; no resources should be allocated."""

    exit_code = ExitCode.INVALID_INPUT


class UnsupportedInputError(ConfigurationError):
    """Input parses but lies outside the supported rehearsal envelope."""

    exit_code = ExitCode.INCONCLUSIVE


class FeatureNotImplementedError(RuntimeError):
    """A planned feature must never silently produce a passing result."""


class RuntimeLifecycleError(RuntimeError):
    """A disposable runtime could not finish its infrastructure lifecycle."""


class ManifestError(RuntimeLifecycleError):
    """Run bookkeeping could not be validated, locked, or persisted."""


class ReadinessTimeout(RuntimeLifecycleError):
    """PostgreSQL did not become ready within its declared deadline."""


class CleanupError(RuntimeLifecycleError):
    """Owned resources or cleanup bookkeeping remain unresolved."""


class RunInterrupted(KeyboardInterrupt):
    """A CLI signal requested bounded teardown."""

    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"Interrupted by signal {signum}")
