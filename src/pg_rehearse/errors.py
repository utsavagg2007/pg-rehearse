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


class FeatureNotImplementedError(RuntimeError):
    """A planned feature must never silently produce a passing result."""
