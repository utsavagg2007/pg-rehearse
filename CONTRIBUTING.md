# Contributing

Use Python 3.12+ and the locked development environment (`uv sync --locked`).
Run `make check` before submitting changes and `make build` when changing packaging.

Keep CLI handlers thin. Docker access belongs to the host runtime; SQL execution
belongs to the worker pipeline; analysis receives evidence rather than live
connections. Planned modules have explicit foundation-stage docstrings. Replace
them only when their feature is implemented and verified.

Update `PROGRESS.md` after every implementation change. Record what works, what is
pending, checks actually run, and the next feature. Do not equate a placeholder,
mocked check, or generated example with a verified database feature.

Write unit tests for decision rules and input validation. Add real PostgreSQL
integration tests alongside the lifecycle and runner implementations. Keep
intentionally incompatible cases separate from infrastructure failures. A missing
required check must never produce a passing rehearsal.

See `IMPLEMENTATION_ORDER.md` for dependencies and acceptance criteria.
