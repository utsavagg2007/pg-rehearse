.PHONY: setup check test integration lint format typecheck build doctor worker-image

setup:
	uv sync --locked

check: lint typecheck test

test:
	uv run --locked pytest

integration:
	uv run --locked pytest --run-docker

worker-image:
	docker build -f docker/worker.Dockerfile -t pg-rehearse-worker:0.1.0 .

lint:
	uv run --locked ruff check .
	uv run --locked ruff format --check .

format:
	uv run --locked ruff check --fix .
	uv run --locked ruff format .

typecheck:
	uv run --locked mypy

build:
	uv build

doctor:
	uv run --locked pg-rehearse doctor
