# Instructions for agents working on StreamSense

## Read authoritative sources first

Start with `docs/README.md`, then the specifications relevant to the task. Requirements and
source precedence are in `docs/sources.md`; unresolved questions are in `docs/decisions.md`.
Use `docs/architecture.md`, `docs/data-model.md`, `docs/api.md`, `docs/security.md`,
`docs/ml-integration.md`, and `docs/design/` as the application specification.
The Figma prototype illustrates interactions; sample metrics and severity values are not
measured results or permission to override the written specification.

## Respect the preparation boundary

This is a Development Readiness submission. Environment setup is allowed. TASK-001 is
**plan only** until the team records its review and instructor implementation approval.
Do not create application tables, migrations, login, uploads, inference, or review features
as part of reviewing that plan. Do not claim team review or client approval on their behalf.

## Approach nontrivial work

1. Read the task, related specifications, current code, and existing tests.
2. Identify affected components, requirements, privacy implications, and missing decisions.
3. Propose a scoped plan with acceptance criteria, verification, and failure behavior.
4. Resolve blocking ambiguities with the team before implementing dependent behavior.
5. Once authorized, make focused changes, run relevant checks, and report results honestly.

Routine implementation details may be chosen and explained. Changes to product scope,
label meaning, evaluation splits, retention, access policy, or client hosting require a
recorded team/client decision as applicable. Continue independent work while questions are open.

## Architectural constraints

- React/TypeScript owns presentation. FastAPI owns authorization and workflow.
- GPU inference and media decoding run in a separate worker; HTTP requests enqueue jobs.
- PostgreSQL stores metadata and state. Private media and checkpoints stay outside Git.
- Keep API contracts and research outputs distinct; never silently rename or reinterpret fields.
- Preserve model output separately from human reviews. A confirmation is not crew delivery.
- Do not add live stream ingestion, Slack delivery, automatic stream shutdown, or game-state detection.
- Unknown severity stays unavailable; do not copy image severity onto each defect.
- Validation chooses models/prompts/thresholds. The final test set stays locked.
- Never fabricate metrics, inference results, overlays, test success, or deployment status.

## Verification

Use `make setup` with committed lockfiles and `make verify` before proposing a merge.
The baseline checks are Python lint/format, pytest, frontend lint, TypeScript and production build.
For TASK-001, also test migrations and constraints against real disposable PostgreSQL;
SQLite is not a substitute for PostgreSQL JSONB/constraint behavior.
For later behavior, add focused tests for authorization, invalid inputs, concurrent reviews,
worker retries, and provenance. Do not add tests that merely repeat static implementation details.
Report skipped checks and missing services. Update `docs/readiness/verification.md` when
preparation evidence changes; never turn an unexecuted check into a pass.

## Files, secrets, and collaboration

Keep secrets in ignored environment files. Never commit client media, label rows, model
predictions, checkpoints, signed links, personal contact information, or meeting recordings.
Use synthetic data for tests and examples. Do not upload client assets to external services.
Review staged paths and contents before publishing; `.gitignore` is not an enforcement guarantee.
Work on a branch and submit a focused pull request. Do not overwrite teammates' changes.
Do not change deployment/account permissions or publish a live service as part of local setup.
