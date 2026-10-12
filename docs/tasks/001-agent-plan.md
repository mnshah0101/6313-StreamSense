# Proposed plan for the first task

**Prepared October 11, 2026. Not implemented. Team review pending.**

The first task is to create four connected database tables. This plan explains how an agent
would do that after approval. A database migration is a saved script that creates or changes
tables; it makes setup repeatable for every developer.

## What the agent checked

- The main app repository at `d8a81704d775c029372526d3458799d4ce5e790d` contained only a README.
- The research repository at `22a39b63526a696595ee5eb42b9bc790514464b9` contained model training,
  data processing, evaluation and tests, but no application database.
- The detailed design supplies the table fields and relationships. The iteration plan explains
  why later features need them. The October 9 meeting supports background analysis jobs.
- The new starter setup runs a basic API and web page. Database tools are installed, but the
  table definitions and setup scripts have not been written.
- Login sessions, access rules, retries and several later records still need design decisions.
  They are left out of this first task rather than filled in with guesses.

## Steps to take after approval

1. **Confirm approval and check the starting point.** Read `AGENTS.md`, the task and related
   documents again. Check teammates' latest changes, confirm team/instructor approval, and
   run `make verify` before changing anything.
2. **Set up the database connection.** Add connection code under `backend/app/db/` using
   SQLAlchemy. Read the address from `DATABASE_URL` and give a clear error if it is missing.
   Keep passwords out of logs and limit open connections. Importing a module or requesting
   `/health` must not connect to the database.
3. **Define the four tables.** Follow `data-model.md` for Account, ModelVersion, MediaAsset and
   AnalysisJob. Preserve required and optional fields, IDs, timestamps, links and allowed values.
   Add checks for unique values, JSON-object permissions and a positive sampling interval.
   Name the database rules and add the listed indexes. Require explicit IDs/timestamps and block
   deletion of a parent record while other records depend on it. Do not add real users or model data.
4. **Write the repeatable setup script.** Configure Alembic to use the same table definitions
   and database address. Review its generated migration. Create accounts/models before assets/jobs;
   remove tables in the opposite order when undoing the migration. Do not import the research tools.
5. **Test on a disposable PostgreSQL database.** Test a valid set of made-up records, duplicates,
   invalid values, missing required values, broken links and blocked deletions. Run setup twice,
   then undo and rerun it. Local checks must clearly report a missing database; the required GitHub
   database check must fail rather than quietly skip its tests.
6. **Add GitHub checks and instructions.** Give CI a PostgreSQL 17 test service and test-only
   credentials. Run the new migration/database tests and all existing checks. Explain how to set
   `DATABASE_URL`; do not default to a hosted database that might contain real data.
7. **Review and report.** Check that only the four planned tables were added and that no private
   data, new app endpoints or research changes slipped in. Report the checks, results and remaining
   limits, then submit the changes for team review.

## Files expected to change

| Location | Purpose |
| --- | --- |
| `backend/app/db/` | Database connection code and the four table definitions |
| `alembic.ini`, `backend/migrations/` | Database setup settings and the first migration |
| `backend/tests/` | Tests using real PostgreSQL and made-up records |
| `.github/workflows/verify.yml`, `Makefile` | Commands and automated database checks |
| `docs/development.md` | Instructions for running and checking the database |

Change the specifications only if the team approves a correction, and keep a record of that change.

## How the checks prove completion

The AC numbers refer to the [task's acceptance criteria](001-database-foundation.md).

| Check | Criteria covered |
| --- | --- |
| Create tables, check the table list, repeat setup, undo and rerun | AC-01, AC-05 |
| Save/read made-up records with correct IDs, links, permissions and timestamps | AC-02, AC-04 |
| Reject duplicates, invalid values and broken links | AC-03 |
| Block unsafe parent deletion and check the planned indexes | AC-06 |
| Run local/GitHub checks and review instructions/private-data handling | AC-07, AC-08 |

No GPU or model run is needed. Use PostgreSQL, not SQLite, because the database-specific fields
and rules must be tested. Undoing migrations is destructive and must be tested only on disposable
databases. Handling real deployments and data deletion needs a later plan.

## Agent's assessment — for the team to discuss

This task provides records needed by several later features without guessing unresolved login,
hosting or worker rules. It also fits the assignment's requirement to plan before implementation.
The team should consider these limits:

- If login or the API design is a better first task, replace this task and review a new plan.
- Storing permissions as JSON does not make access checks work; that is later implementation.
- Some fields needed by later features are still missing from the design (D-02, D-07, D-09).
- Blocking deletion is the proposed starting rule, not the final data-retention policy.
- PostgreSQL was unavailable during preparation, so the task must prove the database setup works.
- The app still needs a tested translation between research results and its own result format.

## Stop here for this assignment

The steps above have not been implemented. The current branch contains documents, software
setup and checks only. The team must record its own feedback in the review worksheet before
implementation starts. This agent assessment does not count as a team review.
