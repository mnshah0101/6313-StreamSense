# Instructions for agents working on StreamSense

## Read the project documents first

Start with `docs/README.md`, then read the documents needed for the task. `docs/sources.md`
explains where requirements came from. `docs/decisions.md` lists questions the team still needs
to answer. The architecture, data, API, security, ML and design documents describe the planned app.
Figma shows proposed interactions; its example scores and severity ratings are not measured results.

## Stop at the assignment's limit

This is a Development Readiness submission. Preparing the environment is allowed. TASK-001 is
**plan only** until the team records its review and the instructor approves implementation.
Do not build its database tables, migration scripts, login, uploads, analysis or review features
while reviewing the plan. Never claim that a teammate, client or instructor approved something
unless that approval has actually been recorded.

## How to approach larger tasks

1. Read the task, relevant documents, existing code and tests.
2. Identify what must change, how it affects private data, and what is still unclear.
3. Propose a plan with a clear scope, completion criteria, tests and expected failure handling.
4. Ask the team about decisions that must be settled before the affected work can begin.
5. Once approved, make focused changes, run the checks and report the results honestly.

You may choose and explain routine coding details. Changes to project scope, label meaning,
data splits, data retention, access rules or hosting need a recorded team/client decision as
appropriate. Continue work that does not depend on an unanswered question.

## Follow the chosen design

- React/TypeScript handles the screens. FastAPI checks access and handles app requests.
- A separate background worker decodes videos and runs the model. API requests add jobs to a queue.
- PostgreSQL stores records and job status. Private media and saved models stay outside Git.
- Translate research outputs into the app's format explicitly; do not silently change field meanings.
- Keep model results separate from human reviews. Confirming an alert does not notify a crew.
- Do not add production-stream access, Slack delivery, automatic shutdown or game-state detection.
- Leave unknown severity unavailable; do not copy an image's severity onto each defect.
- Use validation data to choose models, prompts and thresholds. Keep the final test set locked.
- Never invent results, heat maps, passing tests or deployment status.

## Check the work

Use `make setup` and `make verify` before proposing a merge. The saved dependency versions must
stay reproducible. Checks cover Python code style/tests and frontend code style, types and build.
For TASK-001, test database setup scripts and rules on a disposable PostgreSQL database.
SQLite cannot prove that PostgreSQL's JSONB fields and rules behave correctly.
For later features, test access checks, bad inputs, conflicting reviews, retries and the ability
to trace results to their source. Avoid tests that only repeat the code being tested.
Report missing services and skipped checks. Update `docs/readiness/verification.md` when results
change. A check that was not run is not a pass.

## Protect files and teammates' work

Keep secrets in ignored environment files. Never commit client media, label rows, predictions,
saved models, private viewing links, personal contact details or meeting recordings.
Use made-up test data. Do not upload client assets to external services.
Review the files and their contents before publishing; `.gitignore` alone cannot prevent leaks.
Use a branch and a focused pull request. Do not overwrite teammates' changes, change account
permissions or publish a live service as part of local setup.
