.PHONY: sync format format-check lint typecheck test check build

sync:
	uv sync --python 3.11 --extra dev

format:
	uv run ruff check --fix .
	uv run ruff format .

format-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

typecheck:
	uv run mypy src tests

test:
	uv run pytest

check: format-check lint typecheck test

build:
	uv build --python 3.11
	uv run twine check dist/*
