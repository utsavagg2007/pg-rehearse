# ADR 0001: Python foundation and evidence-first boundaries

Status: accepted for the scaffold, 2026-10-14.

Use Python 3.12+, Typer/Rich, Pydantic/PyYAML, Psycopg 3, Docker SDK, pytest,
Ruff, and mypy. Use a `src` package and an editable installation managed by uv.
Keep exact resolved versions in `uv.lock`. Python 3.14 is selected locally because
it is already available; CI also covers 3.12.

Follow the architecture visible in the shared conversation. The original uploaded
blueprint is not accessible from the public share, so decisions requiring that
document remain open. SQL parsing and HTML rendering dependencies will be selected
when their features are implemented.

Create the complete module layout now, but label unimplemented modules clearly.
Do not invent a successful database run. Preserve separate completion/verdict
fields and explicit exit codes from the start.
