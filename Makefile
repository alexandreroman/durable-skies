.DEFAULT_GOAL := help

##@ App (host, hot reload)

.PHONY: dev
dev: ## Run the frontend and backend in dev mode with hot-reload
	@cd frontend && pnpm install --prefer-offline --silent
	$(MAKE) -j3 worker-dev api-dev ui

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

##@ Infra

.PHONY: infra-up
infra-up: ## Start Temporal dev server + Redis (Temporal gRPC :7233, UI :8233, Redis :6379)
	docker compose up -d --wait temporal redis

.PHONY: infra-down
infra-down: ## Stop Temporal dev server + Redis
	docker compose stop temporal redis

.PHONY: infra-logs
infra-logs: ## Follow Temporal dev server + Redis logs
	docker compose logs -f temporal redis

##@ Stack (Docker)

.PHONY: app-up
app-up: ## Bring up the full stack in Docker (Temporal + Redis + worker + API + frontend)
	docker compose up -d --build

.PHONY: app-down
app-down: ## Tear down the whole Docker stack
	docker compose down

.PHONY: app-logs
app-logs: ## Follow logs from every stack container
	docker compose logs -f

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
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n"} \
		/^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(firstword $(MAKEFILE_LIST))
