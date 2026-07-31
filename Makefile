SHELL := /bin/sh

PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PROCRASTINATE := PYTHONPATH=. $(PYTHON) -m procrastinate --app app.procrastinate_app.procrastinate_app
API_URL ?= http://localhost:8000
LIVE_API_URL ?= https://web-production-e59907.up.railway.app
RAILWAY_ENV ?= production

.DEFAULT_GOAL := help

.PHONY: help setup backend-setup frontend-setup frontend-env \
	db-up db-down db-logs db-schema api worker frontend-dev frontend-start \
	lint test test-backend test-frontend build health health-live \
	deploy deploy-backend deploy-web deploy-worker deploy-frontend

help:
	@echo "Code Delta development commands"
	@echo ""
	@echo "  make setup             Install backend and frontend dependencies"
	@echo "  make db-up             Start local PostgreSQL"
	@echo "  make db-schema         Apply the Procrastinate database schema"
	@echo "  make api               Run the FastAPI server on :8000"
	@echo "  make worker            Run the background comparison worker"
	@echo "  make frontend-dev      Run Vinext on :3000 against LIVE_API_URL"
	@echo "  make lint              Lint backend and frontend"
	@echo "  make test              Run every backend and frontend check"
	@echo "  make build             Build the production frontend"
	@echo "  make health            Check the local backend health endpoint"
	@echo "  make health-live       Check the hosted backend health endpoint"
	@echo "  make deploy-backend    Deploy Railway web and worker services"
	@echo "  make deploy-frontend   Build and deploy the Cloudflare Worker"
	@echo "  make deploy            Deploy backend and frontend"

setup: backend-setup frontend-setup frontend-env

backend-setup:
	python3 -m venv .venv
	$(PIP) install -e ".[dev]"

frontend-setup:
	cd frontend && npm ci

frontend-env:
	@test -f frontend/.env || { \
		echo "NEXT_PUBLIC_CODEDELTA_API_URL=$(LIVE_API_URL)" > frontend/.env; \
		echo "Created frontend/.env"; \
	}

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

db-logs:
	docker compose logs -f postgres

db-schema:
	$(PROCRASTINATE) schema --apply

api:
	$(PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	$(PROCRASTINATE) worker

frontend-dev: frontend-env
	cd frontend && NEXT_PUBLIC_CODEDELTA_API_URL="$(LIVE_API_URL)" npm run dev

frontend-start:
	cd frontend && npm run start

lint:
	$(PYTHON) -m ruff check app tests
	cd frontend && npm run lint

test: lint test-backend test-frontend

test-backend:
	$(PYTHON) -m pytest -q

test-frontend:
	cd frontend && npm test

build:
	cd frontend && npm run build

health:
	curl --fail --silent --show-error "$(API_URL)/health"
	@echo

health-live:
	curl --fail --silent --show-error "$(LIVE_API_URL)/health"
	@echo

deploy: deploy-backend deploy-frontend

deploy-backend: deploy-web deploy-worker

deploy-web:
	railway up --service web --environment "$(RAILWAY_ENV)" --ci -m "Deploy Code Delta web"

deploy-worker:
	railway up --service worker --environment "$(RAILWAY_ENV)" --ci -m "Deploy Code Delta worker"

deploy-frontend: build
	cd frontend && npx wrangler deploy
