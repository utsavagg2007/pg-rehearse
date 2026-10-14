# Foundation-stage build template. The worker entry point refuses to execute
# until scoped roles and the isolated database pipeline are implemented.
FROM ghcr.io/astral-sh/uv:0.12.7 AS uv
FROM python:3.14-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --locked --no-dev --no-editable --python /usr/local/bin/python \
    && useradd --uid 10001 --create-home worker
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
USER 10001
ENTRYPOINT ["/app/.venv/bin/python", "-m", "pg_rehearse.worker"]
