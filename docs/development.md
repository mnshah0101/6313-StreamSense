# Development environment

## What works at this stage

This setup installs the recorded software versions, runs a basic API and web page locally,
and checks the code without needing client data, passwords or a GPU.
The database tables, setup scripts, login, uploads, worker, model analysis and hosted deployment
have not been built. See [verification evidence](readiness/verification.md).

## Prerequisites and installation

- Python 3.11 (`.python-version`; uv can obtain it).
- Node 24.19.0 (`.node-version`) and npm. Activate that version using your normal version manager.
- uv 0.13.0; the CI workflow pins it. See [official uv installation](https://docs.astral.sh/uv/getting-started/installation/).
- Make for the shortcuts below; equivalent commands are also provided.
- Docker Compose is optional until database work. No remote service signup is needed for this starter setup.

Official references: [Node downloads](https://nodejs.org/en/download),
[Vite setup](https://vite.dev/guide/), [FastAPI first steps](https://fastapi.tiangolo.com/tutorial/first-steps/),
[Docker Compose installation](https://docs.docker.com/compose/install/).

```sh
git clone https://github.com/mnshah0101/6313-StreamSense.git
cd 6313-StreamSense
make setup
```

`make setup` is exactly `uv sync --locked` and `npm --prefix frontend ci`.
`uv.lock` and `frontend/package-lock.json` record exact software versions so developers get
the same setup. Update them when intentionally changing dependencies. The API does not load
the separate research software.

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
CI runs the same setup/checks plus `make verify-db` against a disposable PostgreSQL 17 service
on pull requests and main pushes with no client secrets. Hosted
execution is only verified when a successful GitHub Actions run is recorded; a workflow file alone
is not proof of a passing remote run. Fork PRs may require a maintainer to approve the first run.

## Database tools ready for the first task

SQLAlchemy, Alembic and Psycopg are installed in the Python lockfile. The local service uses
PostgreSQL 17, localhost port 5432, a persistent development volume and disposable local-only
credentials. Do not reuse the example password on a hosted service.

```sh
make db-up
export DATABASE_URL='postgresql+psycopg://streamsense:local-development-only@127.0.0.1:5432/streamsense'
make verify-db
# Later, when finished:
make db-stop
```

`make verify-db` connects to the supplied database, checks PostgreSQL major version 17 and
round-trips a JSON object and a timezone-aware timestamp. It creates no tables and changes no
stored records. Missing settings, failed connections and incompatible versions fail the check;
it never silently skips. Error output omits connection details to avoid printing passwords.
Use the local development service or an explicitly disposable test database.

If the check fails, ensure the database is running and healthy, the port is free, the credentials
match the service, and `DATABASE_URL` is exported in the same terminal. The URL must use the
`postgresql+psycopg` driver installed by `make setup`. CI supplies its own disposable credentials.
The API health endpoint remains independent of the database.

No code currently reads `.env`, and no database setup scripts (migrations) exist. TASK-001 will define environment loading,
initialize Alembic and implement/test its first migration after approval. Until then, do not
claim `alembic upgrade head` creates a schema. `db-stop` preserves the local volume. If a developer
later wants to remove that volume, they must intentionally accept losing its local contents.
Local Compose could not be exercised on the preparation machine because Docker is unavailable.
The separate GitHub database check is recorded in the verification record.

## Secrets and data

Environment files are ignored except `.env.example`. Never put secrets in `VITE_*` variables;
those become browser-visible. Keep client assets/checkpoints outside the repository and use
synthetic data for local/CI tests. Do not publish original source PDFs or private meeting links.
The security specification governs any later demo with real media.
