# Project documents

> **Status (November 2026):** these are the October planning and readiness documents. The system
> is now built: see the [root README](../README.md) for what exists, the measured results, and how
> to run it, and `ml/`, `backend/`, `frontend/` for each part. Where the code and these plans
> differ (for example SQLite in development instead of PostgreSQL, a lease-based worker queue,
> S3 instead of Vercel Blob, session sign-in before OIDC), the code and its READMEs are current.

These documents explain what we plan to build and what a developer needs to know before starting.
They are based on the team's earlier work. Chang has confirmed the team's review and agreement;
see the [review record](readiness/team-review.md). Unresolved decisions remain listed separately.

**Start with the architecture, user flows and first task.** The database and API documents contain
more detail for whoever builds those parts. The [short glossary](glossary.md) explains technical
terms used throughout the documents.

| Document | What it explains |
| --- | --- |
| [Sources and requirements](sources.md) | Where the requirements came from |
| [Architecture](architecture.md) | The main parts of the app and how they work together |
| [Data model](data-model.md) | What the database stores and how records connect |
| [API and interfaces](api.md) | How the screens, server and model exchange information |
| [Security and privacy](security.md) | Who can access data and how we protect it |
| [ML integration](ml-integration.md) | How the existing model research will connect to the app |
| [UI specification](design/ui-spec.md) | What each screen needs to show and do |
| [User flows](design/user-flows.md) | The steps a user takes to complete each task |
| [Decisions still needed](decisions.md) | What is settled and what the team must decide |
| [Development guide](development.md) | How to install, run and check the starter setup |
| [First task](tasks/001-database-foundation.md) | The first piece of implementation work we propose |
| [Review guide and rubric evidence](readiness/review-guide.md) | How to explain the project and critically examine the first plan |

The app will analyze uploaded sports footage. The course demo will use videos to simulate
multiple streams and show results as they arrive. Model research already exists in a separate
repository. This repository currently contains only the starter setup and preparation documents.
