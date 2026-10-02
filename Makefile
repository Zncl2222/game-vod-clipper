.PHONY: setup lint security test test-web build check

setup:
	uv sync --frozen --all-extras
	npm --prefix web ci

lint:
	uv run --frozen ruff check src tests scripts web/tests
	npm --prefix web run lint
	npm --prefix web run typecheck

security:
	uv run --frozen bandit -c pyproject.toml -r src scripts -ll
	mkdir -p runs/security
	uv export --frozen --all-extras --no-emit-project --format requirements-txt -o runs/security/requirements.txt > /dev/null
	uv run --frozen pip-audit --strict --disable-pip --require-hashes -r runs/security/requirements.txt

test:
	uv run --frozen --all-extras python -m unittest discover -s tests -v

test-web: build
	npm --prefix web run test:chat
	npm --prefix web run test:youtube
	npm --prefix web run test:e2e
	npm --prefix web run test:storage

build:
	npm --prefix web run build

check: lint security test build
