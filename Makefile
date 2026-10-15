.PHONY: setup check test integration lint format typecheck build doctor

setup:
	uv sync --locked

check: lint typecheck test

test:
	uv run --locked pytest

integration:
	uv run --locked pytest --run-docker

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
