.DEFAULT_GOAL := help

##@ Development

.PHONY: install
install: ## Install dependencies
	uv sync

.PHONY: worker
worker: ## Run the Temporal worker
	uv run durable-skies-worker

.PHONY: api
api: ## Run the HTTP/WS API for the UI
	uv run durable-skies-api

.PHONY: worker-dev
worker-dev: ## Run worker with auto-reload on file changes
	uv run -- watchfiles 'python -m durable_skies' src/

.PHONY: api-dev
api-dev: ## Run API with auto-reload on file changes
	uv run -- watchfiles 'durable-skies-api' src/

##@ Quality

.PHONY: lint
lint: ## Run linter
	uv run ruff check .

.PHONY: format
format: ## Format code
	uv run ruff format .

.PHONY: test
test: ## Run tests
	uv run pytest

##@ Helpers

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' \
		$(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "\033[36m%-15s\033[0m %s\n", \
		$$1, $$2}'
