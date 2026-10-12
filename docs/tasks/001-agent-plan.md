# Agent-proposed implementation plan — TASK-001

**Prepared October 11, 2026. Not implemented. Team review pending.**

## Investigation performed

- Inspected the main repository at `d8a81704d775c029372526d3458799d4ce5e790d`: only a README.
- Inspected the separate research repository at `22a39b63526a696595ee5eb42b9bc790514464b9`:
  Python model/data/evaluation modules, locked dependencies, tests and Slurm tooling; no app database.
- Reviewed S2's architecture, core table fields and ERDs; S3's setup dependencies; S4's client
  requirements; S10's async job direction; and the prototype's relevant screens.
- Inspected the preparation scaffold: FastAPI health only, a static React preparation page,
  Python/JS lockfiles, checks and optional PostgreSQL Compose service. SQLAlchemy/Alembic/Psycopg
  dependencies are installed, but there are no ORM models or migrations.
- Identified schema gaps affecting later work (sessions/access, retries, failure records,
  idempotency, evaluation subsets). They are explicitly excluded from this task rather than
  guessed into the initial migration.

## Proposed sequence after approval

1. **Check authorization and baseline.** Read `AGENTS.md`, task/specs/decision register and current
   Git state again. Confirm team/instructor approval. Run `make verify` before changing behavior.
2. **Introduce database configuration.** Add `backend/app/db/` for a SQLAlchemy base and engine/session
   factory. Read a supplied `DATABASE_URL`; fail clearly when missing. Do not connect at module
   import or from `/health`. Keep credentials out of logs and use bounded connections.
3. **Define the four core models.** Implement the exact field/nullability/relationship contract in
   `data-model.md`, explicit UUID/timestamp values, role/status checks, JSON-object permissions,
   unique keys, positive sample interval and documented indexes. Use named constraints and
   restrictive parent deletes. Do not add hidden defaults or seed real users/model records.
4. **Initialize Alembic.** Add a root configuration and a migrations directory connected to the same
   model metadata/URL. Generate and manually inspect the initial migration: parent tables first,
   then asset and job; reverse dependency order on downgrade. No imports from the research stack.
5. **Verify on disposable PostgreSQL.** Add integration fixtures using isolated test state, run fresh
   upgrade, duplicate/invalid/FK/nullability checks, valid synthetic chain, deletion restriction,
   second upgrade and downgrade/re-upgrade. Fail or explicitly skip when a local DB is unavailable;
   the dedicated CI database job must fail rather than silently skip required coverage.
6. **Extend CI and run instructions.** Add a PostgreSQL 17 service with a health check and test-only
   credentials. Run migrations and integration tests plus existing checks. Document how developers
   supply `DATABASE_URL`; migration commands must not default to a hosted database.
7. **Review the diff and evidence.** Confirm only four tables were introduced; no secrets, client
   assets, endpoint implementation or research changes. Report commands, results and remaining
   limits, then present the PR for team review.

## Expected files

- `backend/app/db/`: configuration, base/session utilities and the four model definitions.
- `alembic.ini`, `backend/migrations/`: Alembic environment and reviewed initial revision.
- `backend/tests/`: real-PostgreSQL constraint and migration tests using synthetic data.
- `.github/workflows/verify.yml`, `Makefile`, `docs/development.md`: explicit database verification.
- Existing core specifications only if team-approved corrections are needed; preserve their history.

## Validation mapped to acceptance

| Checks | Criteria |
| --- | --- |
| Fresh upgrade, schema inventory, repeat upgrade, downgrade/re-upgrade | AC-01, AC-05 |
| Synthetic insert/readback, exact FK/UUID/JSON/timezone behavior | AC-02, AC-04 |
| Uniqueness, invalid enum, JSON type, positive interval and FK failures | AC-03 |
| Restricted parent deletion and index inspection | AC-06 |
| Full local/CI checks with PostgreSQL, diff/privacy review | AC-07, AC-08 |

No GPU or actual inference is needed. Do not substitute SQLite for PostgreSQL's JSONB behavior.
Rollback checks are safe only on disposable test databases. Production migration rollback and
retention/deletion services require a later operational design.

## Agent's critical assessment — not a team review

The plan follows the stated relational architecture and async job dependency, and keeps product
implementation outside readiness preparation. Its four-table scope avoids guessing unresolved
provider, permission and worker policies. Risks to discuss:

- A database task is useful before features, but the team may prefer identity or API contract work
  first. If so, replace the task and regenerate its plan before claiming review.
- JSONB permissions are structurally constrained here but do not implement authorization.
- The design's full schema omits fields needed by later services; D-02/D-07/D-09 remain real gates.
- Restrictive deletion is safe for this foundation but is not the final retention/anonymization policy.
- PostgreSQL was not available during preparation; the first task must prove migrations on it.
- The application still needs a separately validated translation from research predictions.

## Stop here

No step above has been executed as feature implementation. The current branch only prepares
specifications, dependencies, local scaffold and verification. The team must use the review worksheet
to record its own assessment before implementation begins.
