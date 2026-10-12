UV ?= uv
NPM ?= npm

.PHONY: setup verify api web db-up db-stop
setup:
	$(UV) sync --locked
	$(NPM) --prefix frontend ci

verify:
	$(UV) run --locked ruff check .
	$(UV) run --locked ruff format --check .
	$(UV) run --locked pytest
	$(NPM) --prefix frontend run lint
	$(NPM) --prefix frontend run build

api:
	$(UV) run --locked uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload

web:
	$(NPM) --prefix frontend run dev

db-up:
	docker compose up -d db

db-stop:
	docker compose stop db
