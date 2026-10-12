# TASK-001 — Establish the core PostgreSQL schema and migrations

**Status: proposed; plan only. Implementation has not started.**
Owner: assign during team review. Approval: pending team review and instructor go/no-go.

## Why this is first

The main app currently has no database schema. Uploads, jobs, authorization and inference provenance
all need a consistent storage foundation. S3's Global Setup and later feature dependencies call for
data/database setup; S2 Figures 4–5 define the records. Existing research files are not an application
database. A schema task is meaningful and can be tested locally without client data or a GPU.

## Scope

Create a reversible Alembic migration and SQLAlchemy metadata for exactly:
`Account`, `ModelVersion`, `MediaAsset`, and `AnalysisJob`, using the core schema in
[`data-model.md`](../data-model.md). Add database configuration that reads `DATABASE_URL`,
an example/local setup guide, and real-PostgreSQL integration tests.

Use UUID keys, timezone-aware timestamps, JSONB permissions, required FKs, explicit role/job-status
checks, unique account subject and asset object key, a positive sampling interval and the documented
indexes. Proposed first-task deletion policy is restrictive: dependent records block deletion until
a later explicit deletion service coordinates cleanup. Do not seed real accounts/model manifests.

No HTTP route may expose these records yet. Authentication, upload verification, workers, video
decoding, alert/review tables, evaluation tables, model inference and production deployment are excluded.
Do not modify the research repository or its locked test split.

## Acceptance criteria

| ID | Observable condition |
| --- | --- |
| AC-01 | A fresh disposable PostgreSQL 17 database accepts `alembic upgrade head`; exactly the four application tables plus Alembic's version table exist. |
| AC-02 | A synthetic account/model/asset/job chain inserts successfully and retains the expected UUID relationships, JSON object permissions and timezone-aware timestamps. |
| AC-03 | Duplicate subject/object key, missing parent FK, invalid role/job status, non-object permissions and nonpositive sample interval are rejected by database constraints. |
| AC-04 | Required field nulls are rejected; nullable metadata/lease/failure fields accept null without fabricated values. |
| AC-05 | `upgrade head` twice is safe; `downgrade base` then `upgrade head` works on a disposable database. Destructive migration testing never targets client data. |
| AC-06 | Deleting a referenced parent fails under the proposed restrictive policy; documented indexes are present. |
| AC-07 | Real-PostgreSQL integration tests run locally and in CI alongside the existing checks; no credentials/client records are committed or logged. |
| AC-08 | README/development instructions explain database start, configuration, migration, verification and failure diagnosis; no application feature is claimed complete. |

## Ready-to-start prerequisites

- Team reviews `001-agent-plan.md` and records corrections/acceptance in the review worksheet.
- Instructor implementation permission is recorded.
- PostgreSQL 17 is available locally or as a disposable CI service.
- Team accepts the first-task details: four-table boundary, JSON-object-only permission container,
  explicit IDs/timestamps and restrictive deletes. Permission semantics remain a later task.

## Stop condition

For this Development Readiness assignment, stop after proposing/reviewing the plan. Do not create
ORM models, Alembic environment files or migrations now. The dependency tooling and optional local
PostgreSQL service are preparation only. Record the plan's review honestly; AI cannot approve it
on behalf of Moksh, Thomas, Chang or the instructor.
