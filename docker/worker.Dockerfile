# Build explicitly; runs use this image's resolved immutable content ID.
FROM ghcr.io/astral-sh/uv:0.12.7 AS uv
FROM python:3.14-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --locked --no-dev --no-editable --python /usr/local/bin/python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
USER 10001:10001
ENTRYPOINT ["/app/.venv/bin/python", "-m", "pg_rehearse.worker"]
