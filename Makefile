.PHONY: setup check test integration evaluate lint format typecheck build package-check doctor worker-image

setup:
	uv sync --locked

check: lint typecheck test

test:
	uv run --locked pytest

integration:
	uv run --locked pytest --run-docker

evaluate:
	uv run --locked python scripts/evaluate.py

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
	uv run --locked python -m build --no-isolation

package-check: build
	uv run --locked python scripts/check_distributions.py

doctor:
	uv run --locked pg-rehearse doctor
