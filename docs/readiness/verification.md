# Preparation verification record

Prepared October 11, 2026. Local checks were executed as recorded below; hosted CI is tracked separately. This record covers only the development scaffold, not product acceptance.

## Scope

No application schema, migrations, authentication, inference, uploads or review features were
implemented. The research repository was inspected, not retrained or rerun. Client data and GPUs
were not used. Team review and instructor approval remain pending.

## Environment and checks

Preparation host: macOS arm64; Python 3.11.17, Node 24.19.0, uv 0.13.0.

| Check | Observed result |
| --- | --- |
| `uv sync --locked` | PASS; API and development dependencies installed from `uv.lock` |
| `npm --prefix frontend ci` | PASS; frontend dependencies installed from committed lockfile |
| `uv run --locked ruff check .` | PASS |
| `uv run --locked ruff format --check .` | PASS |
| `uv run --locked pytest` | PASS; 2 scaffold tests, 1 upstream deprecation warning |
| `npm --prefix frontend run lint` | PASS; Oxlint |
| `npm --prefix frontend run build` | PASS; TypeScript and Vite production build |
| API server + `GET /health` | PASS; HTTP 200, process liveness/preparation stage only |
| Frontend in browser | PASS; preparation page renders and states product features await approval |
| Internal Markdown links | PASS; all relative document links resolve |
| Git whitespace check | PASS |
| Hosted GitHub Actions | Pending; workflow included, remote status must be checked on the PR |

The pytest warning is from Starlette's test client deprecating its `httpx` integration in favor
of `httpx2`; it did not fail either test. Resolve it in a dependency-maintenance change rather
than hide warnings. These two tests do not validate product behavior, database or security features.

## Checks requiring later resources/work

- PostgreSQL service/migrations: Docker is unavailable on the preparation machine; no schema
  exists before TASK-001. Compose is provided, not reported as an exercised database.
- GPU inference, latency, throughput and model quality: not tested by this application scaffold.
- OIDC, Vercel/Blob, managed database and worker deployment: not configured or tested.
- Product user flows/security tests: future feature work, not covered by two scaffold tests.
- Team review and Go/No-Go permission: must be supplied by the team/instructor.
