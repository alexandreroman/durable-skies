.DEFAULT_GOAL := dev

##@ Run

.PHONY: dev
dev: ## Run the frontend and backend in dev mode with hot-reload
	@cd frontend && pnpm install --prefer-offline --silent
	$(MAKE) -j3 worker-dev api-dev ui

.PHONY: app
app: ## Run the full stack in containers
	docker-compose up

.PHONY: worker
worker: ## Run the Temporal worker
	$(MAKE) -C backend worker

.PHONY: api
api: ## Run the HTTP API
	$(MAKE) -C backend api

.PHONY: worker-dev
worker-dev: ## Run the Temporal worker with auto-reload
	$(MAKE) -C backend worker-dev

.PHONY: api-dev
api-dev: ## Run the HTTP API with auto-reload
	$(MAKE) -C backend api-dev

.PHONY: ui
ui: ## Run the Nuxt dev server
	$(MAKE) -C frontend dev

##@ Infrastructure

.PHONY: infra-up
infra-up: ## Start Temporal dev server + Redis (Temporal gRPC :7233, UI :8233, Redis :6379)
	docker-compose up -d temporal redis

.PHONY: infra-down
infra-down: ## Stop local Temporal
	docker-compose down

##@ Quality

.PHONY: lint
lint: ## Lint backend and frontend
	$(MAKE) -C backend lint
	$(MAKE) -C frontend lint

.PHONY: format
format: ## Format backend and frontend
	$(MAKE) -C backend format
	$(MAKE) -C frontend format

##@ Helpers

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
