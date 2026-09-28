PROJECT := bm_tracker
SOURCES := $(PROJECT) tests alembic
CONTAINER_ENGINE := $(shell command -v podman 2>/dev/null || command -v docker)

# Local development database. A path rather than a URL so that `make dev` works
# from a clean checkout with no .env file present.
DEV_DB := $(CURDIR)/data/bm_tracker.db
DEV_ENV := APP_ENV=development
DEV_ENV_URL := $(DEV_ENV) DATABASE_URL=sqlite+aiosqlite:///$(DEV_DB)

.DEFAULT_GOAL := help

.PHONY: help
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup:  ## Install dependencies and the pre-commit hooks
	uv sync --all-groups
	uv run pre-commit install

.PHONY: format
format:  ## Auto-format code with ruff
	uv run ruff check --fix $(SOURCES)
	uv run ruff format $(SOURCES)

.PHONY: lint
lint:  ## Lint with ruff, check types with ty, and scan for secrets
	uv run ruff check $(SOURCES)
	uv run ruff format --diff $(SOURCES)
	uv run ty check $(SOURCES)
	$(MAKE) lint-secrets

.PHONY: lint-secrets
lint-secrets:  ## Scan the working tree for secrets
	@command -v gitleaks >/dev/null 2>&1 || { \
		echo "gitleaks is not installed, so secrets were NOT scanned."; \
		echo "Install it with:  brew install gitleaks"; \
		echo "  or download https://github.com/gitleaks/gitleaks/releases"; \
		echo "This check is deliberately fatal: claiming secrets are clean"; \
		echo "without running the scanner is worse than not checking."; \
		exit 1; \
	}
	@gitleaks dir --no-banner --redact .

.PHONY: test
test:  ## Run the test suite
	uv run pytest

.PHONY: test-cov
test-cov:  ## Run tests with a coverage report
	uv run pytest --cov=$(PROJECT) --cov-report=term-missing

.PHONY: build
build:  ## Build the OCI image
	@if [ -z "$(CONTAINER_ENGINE)" ]; then \
		echo "No podman or docker found; cannot build the image."; \
		exit 1; \
	fi
	$(CONTAINER_ENGINE) build \
		--build-arg SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 \
		-t bm-tracker:latest .

.PHONY: clean
clean:  ## Remove build artifacts and caches
	rm -rf dist build .coverage htmlcov .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete

.PHONY: migrate
migrate:  ## Apply database migrations
	$(DEV_ENV_URL) uv run alembic upgrade head

# --- local development ---------------------------------------------------

.PHONY: dev-db
dev-db:  ## Create the local database and migrate it to head
	@mkdir -p $(dir $(DEV_DB))
	$(DEV_ENV_URL) uv run alembic upgrade head
	@echo "local database ready: $(DEV_DB)"

.PHONY: dev-reset
dev-reset:  ## Wipe the local database and rebuild it from scratch
	rm -f $(DEV_DB) $(DEV_DB)-wal $(DEV_DB)-shm
	$(MAKE) dev-db
	@echo
	@echo "Fresh local database at $(DEV_DB)"
	@echo "No accounts exist yet — account creation lands in Phase 3."

.PHONY: dev-seed
dev-seed:  ## Rebuild the local database with fake users and history
	rm -f $(DEV_DB) $(DEV_DB)-wal $(DEV_DB)-shm
	$(DEV_ENV_URL) uv run bm-tracker seed
	@echo
	@echo "Sign in at http://127.0.0.1:8000 as 'cal' (or any seeded user)"
	@echo "with the password printed above. 'cal' is the admin."

.PHONY: dev
dev:  ## Run the app on http://127.0.0.1:8000 with auto-reload
	$(DEV_ENV_URL) uv run uvicorn $(PROJECT).app:create_app --factory \
		--host 127.0.0.1 --port 8000 --reload
