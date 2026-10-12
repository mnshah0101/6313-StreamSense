# Preparation verification record

Prepared October 11, 2026. Local checks were executed as recorded below; hosted CI is tracked separately. This record covers only the development scaffold, not product acceptance.

## Scope

No application schema, migrations, authentication, inference, uploads or review features were
implemented. The research repository was inspected, not retrained or rerun. Client data and GPUs
were not used. Team acceptance has been confirmed by Chang; instructor implementation approval remains pending.

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
| Hosted GitHub Actions | PASS on main commit `6dc7cf01a165dd748a491e2de875ef7da1b06680`; [run 38193532635](https://github.com/mnshah0101/6313-StreamSense/actions/runs/38193532635) completed successfully |

The pytest warning is from Starlette's test client deprecating its `httpx` integration in favor
of `httpx2`; it did not fail either test. Resolve it in a dependency-maintenance change rather
than hide warnings. These two tests do not validate product behavior, database or security features.

## Checks requiring later resources/work

- PostgreSQL migrations/constraints: not implemented or tested before TASK-001.
- Local Compose: Docker is unavailable on the preparation machine; CI connectivity is a separate check.
- GPU inference, latency, throughput and model quality: not tested by this application scaffold.
- OIDC, Vercel/Blob, managed database and worker deployment: not configured or tested.
- Product user flows/security tests: future feature work, not covered by two scaffold tests.
- Instructor Go/No-Go permission: still required before feature implementation.
- Independent setup runs by each teammate: not recorded; local checks were performed by the agent.

## Publication

[Pull request #1](https://github.com/mnshah0101/6313-StreamSense/pull/1) was merged into main
at Chang's request after write access became available. The automated GitHub checks then passed.
Team acceptance is recorded separately in `team-review.md`; passing checks do not prove model
quality, production security or individual team understanding.

## Readability update

The documents were revised to explain the purpose of each step in plain language, with a short
glossary for technical terms. Exact database fields, API paths and setup commands remain in the
detailed references. Internal document links and whitespace were checked again. This update
changed documentation only; it did not change code or the earlier test results.

## Additional readiness checks

The readiness update adds `make verify-db` and a disposable PostgreSQL 17 service in GitHub
Actions. This checks connectivity, JSONB and timezone-aware timestamp handling without creating
application tables or migrations. **PASS:** [run 38195521600](https://github.com/mnshah0101/6313-StreamSense/actions/runs/38195521600)
completed all checks, including `make verify-db`, using the update at `a86c307` through PR #3.
This is an observed real PostgreSQL connection in GitHub, not a claim that local Docker ran.

Local verification was repeated after the update: Python checks, both scaffold tests, frontend
lint and frontend build passed. The database command was also checked with a missing URL, an
unavailable service and a non-PostgreSQL URL. All three returned failure without printing the
connection details. Those negative checks verify error handling; the hosted run above supplies successful connection evidence.
All 47 relative Markdown links resolved, and the Git whitespace check passed.

The new [review guide](review-guide.md) maps all five rubric categories to evidence and explains
the plan's tradeoffs. It supports team preparation; it does not certify individual understanding
or guarantee a grade.
