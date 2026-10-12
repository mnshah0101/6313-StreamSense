# First task: set up the core database

**TASK-001 — proposed; planning only. Implementation has not started.**
The team will assign an owner during review. Team review and instructor approval are pending.

## Why start here?

The app needs a place to record who uploaded a file, which model to use and what work is waiting.
Those records support later upload, login and analysis features. The detailed design already
shows their fields and relationships. The research repository does not provide this app database.

## What to build after approval

Create these four PostgreSQL tables:

| Table | What it records |
| --- | --- |
| Account | A user and their account information |
| ModelVersion | The exact saved model and settings used for analysis |
| MediaAsset | An uploaded file, its owner and its private storage reference |
| AnalysisJob | A request to analyze one file using one model |

Use the field definitions in [the data model](../data-model.md). Write an Alembic migration:
a saved script that creates the tables and can undo that setup on a test database. Use SQLAlchemy
to define the tables in Python, and read the database connection from `DATABASE_URL`.

Preserve the specified record IDs, timestamps, required links, allowed roles/job states and unique
values. Permissions must be a JSON object, and the sampling interval must be positive. Add the
listed indexes to support record lookups. Use explicit IDs and timestamps rather than hidden
defaults. The proposed starting rule blocks deletion of records that other records still need.
The team must review that rule; the full deletion policy is later work.

Do not add real accounts, saved model records or client files. This task does not build login,
API routes, uploads, workers, video processing, alerts, reviews or deployment. It does not change
the research code or its final test data.

## How we will know the task is complete

| ID | Required result |
| --- | --- |
| AC-01 | On a fresh PostgreSQL 17 test database, `alembic upgrade head` creates exactly the four app tables plus Alembic's own version table. |
| AC-02 | Made-up account, model, asset and job records can be saved and read back with correct IDs, links, JSON permissions and timezone-aware timestamps. |
| AC-03 | The database rejects duplicate account subjects/file keys, missing linked records, invalid roles/job states, non-object permissions and sampling intervals of zero or less. |
| AC-04 | Required fields cannot be empty. Fields marked optional accept null without made-up replacement values. |
| AC-05 | Running setup twice is safe. Undoing setup with `downgrade base` and rerunning it works on a disposable database only. |
| AC-06 | Deleting a record that other records depend on is blocked. The planned indexes exist. |
| AC-07 | Tests run against real PostgreSQL locally and on GitHub, alongside existing checks. No passwords or client data are committed or logged. |
| AC-08 | The development guide explains how to start the database, supply settings, run migrations, check results and diagnose failures. It does not claim other app features are finished. |

## Before starting

- Review [the proposed plan](001-agent-plan.md) and record team feedback in the review worksheet.
- Record the instructor's approval to begin implementation.
- Have PostgreSQL 17 available locally or in a disposable CI service.
- Agree on the four-table scope, permission storage, explicit IDs/timestamps and deletion rule.
  The meaning of individual permissions will be decided in the later access-control task.

## Assignment stopping point

Stop after preparing and reviewing the plan. Do not create table definitions or migration files
for this assignment. Installing database tools and providing a local database configuration are
preparation only. AI cannot approve the plan on behalf of the team or instructor.
