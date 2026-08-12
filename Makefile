.PHONY: install test lint

install:
	poetry install || uv sync || pip install -e .

test:
	pytest

lint:
	ruff check . || flake8 . || python -m pytest --version
