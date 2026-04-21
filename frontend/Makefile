.DEFAULT_GOAL := help

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies
	pnpm install

dev: ## Start dev server with hot reload
	pnpm dev

build: ## Build for production
	pnpm build

preview: ## Preview the production build
	pnpm preview

generate: ## Static-generate the site
	pnpm generate

typecheck: ## Type-check without emitting
	pnpm typecheck

lint: ## Run linter
	pnpm lint

lint-fix: ## Run linter with auto-fix
	pnpm lint:fix

format: ## Format all files
	pnpm format
