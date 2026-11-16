# StreamSense: ml/ (research), backend/ (API + worker), frontend/ (web app).
UV ?= uv
NPM ?= npm

.PHONY: setup verify verify-backend verify-ml verify-frontend api web
setup:
	cd backend && $(UV) sync --locked --extra dev
	cd ml && $(UV) sync --locked --only-group dev
	$(NPM) --prefix frontend ci

verify: verify-backend verify-ml verify-frontend

verify-backend:
	cd backend && $(UV) run --locked ruff check . && $(UV) run --locked ruff format --check .
	cd backend && $(UV) run --locked pytest -q

# Lint only here: the ml test suite needs torch (`cd ml && uv sync --extra analysis --extra models`).
verify-ml:
	cd ml && $(UV) run --locked --only-group dev ruff check .

verify-frontend:
	$(NPM) --prefix frontend run build

api:
	cd backend && $(UV) run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

web:
	$(NPM) --prefix frontend run dev
