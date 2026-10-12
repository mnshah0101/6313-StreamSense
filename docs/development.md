# Development environment

## What this setup proves

The repository can install a locked Python API environment and a locked React/TypeScript frontend,
run the local preparation page/API, and execute checks without client data, credentials or a GPU.
No application tables, migrations, auth provider, uploads, worker, model inference or production
hosting have been implemented. See [verification evidence](readiness/verification.md).

## Prerequisites and installation

- Python 3.11 (`.python-version`; uv can obtain it).
- Node 24.19.0 (`.node-version`) and npm. Activate that version using your normal version manager.
- uv 0.13.0; the CI workflow pins it. See [official uv installation](https://docs.astral.sh/uv/getting-started/installation/).
- Make for the shortcuts below; equivalent commands are also provided.
- Docker Compose is optional until database work. No remote service signup is needed for the scaffold.

Official references: [Node downloads](https://nodejs.org/en/download),
[Vite setup](https://vite.dev/guide/), [FastAPI first steps](https://fastapi.tiangolo.com/tutorial/first-steps/),
[Docker Compose installation](https://docs.docker.com/compose/install/).

```sh
git clone https://github.com/mnshah0101/6313-StreamSense.git
cd 6313-StreamSense
make setup
```

`make setup` is exactly `uv sync --locked` and `npm --prefix frontend ci`.
`uv.lock` and `frontend/package-lock.json` control resolved versions; commit intentional lock
changes together with dependency edits. The main API does not import the research environment.

## Run

In separate terminals from the root:

```sh
make api
make web
```

API: `http://127.0.0.1:8000/health`, returning process liveness and preparation stage only.
Frontend: `http://127.0.0.1:5173`, showing an environment-ready message.
Both bind to localhost. Stop with Ctrl+C. The page deliberately has no fake product buttons,
model metrics, login or upload path. Vite may offer another port if 5173 is occupied; use the
address it prints. API startup fails if port 8000 is occupied; free it or explicitly change the port.

Equivalent commands:

```sh
uv run --locked uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
npm --prefix frontend run dev
```

## Verify

```sh
make verify
```

Runs Python lint/format, pytest, frontend lint and TypeScript/build. The two scaffold tests check
that health is process-only and that product endpoints are absent. Future feature tests must
verify behavior and failure boundaries, not simply repeat implementation.
CI runs the same setup/checks on pull requests and main pushes with no client secrets. Hosted
execution is only verified when a successful GitHub Actions run is recorded; a workflow file alone
is not proof of a passing remote run. Fork PRs may require a maintainer to approve the first run.

## Database tooling prepared for TASK-001

SQLAlchemy, Alembic and Psycopg are installed in the Python lockfile. The local service uses
PostgreSQL 17, localhost port 5432, a persistent development volume and disposable local-only
credentials. Do not reuse the example password on a hosted service.

```sh
cp .env.example .env  # only if you do not already have a local .env
make db-up
# Later, when finished:
make db-stop
```

No code currently reads `.env`, and no migrations exist. TASK-001 will define environment loading,
initialize Alembic and implement/test its first migration after approval. Until then, do not
claim `alembic upgrade head` creates a schema. `db-stop` preserves the local volume. If a developer
later wants to remove that volume, they must intentionally accept losing its local contents.
The service has not been exercised on a machine without Docker; see the verification record.

## Secrets and data

Environment files are ignored except `.env.example`. Never put secrets in `VITE_*` variables;
those become browser-visible. Keep client assets/checkpoints outside the repository and use
synthetic data for local/CI tests. Do not publish original source PDFs or private meeting links.
The security specification governs any later demo with real media.
