# StreamSense — Development Readiness

Team 6313, Parallax: Moksh Shah, Thomas Li, and Rui Chang Lyu (Chang).
Client: PlayOn; client contact: Vijay Rajagopal.
Course: CX 3803. Preparation date: October 11, 2026.

StreamSense analyzes sports footage for image-quality defects. The model is the client's
main priority; this app supports the required course demo and human review.
The planned demo processes uploaded videos in the background and updates the timelines
as frame results arrive. It does not connect to production streams or stop them.

**Status: team acceptance recorded; prepared for the readiness submission.** Chang confirmed
that the team reviewed and agreed to the documents and proposed plan. This repository contains
project documents and a starter setup that runs locally. The first implementation task is planned,
not built. Instructor implementation approval remains pending for the Go/No-Go Review.

## Assignment entry points

| Deliverable | Start here |
| --- | --- |
| Project specifications | [Project documents](docs/README.md) |
| Instructions the coding agent should follow | [AGENTS.md](AGENTS.md) |
| Run and verify the environment | [Development guide](docs/development.md) |
| First implementation task | [TASK-001: core database](docs/tasks/001-database-foundation.md) |
| Agent investigation and proposed plan | [TASK-001 implementation plan](docs/tasks/001-agent-plan.md) |
| Team's critical review and readiness | [Team review record](docs/readiness/team-review.md) |
| Checks that were actually run | [Verification record](docs/readiness/verification.md) |
| Questions still to answer | [Decision list](docs/decisions.md) |

## Run locally

Prerequisites: Python 3.11, Node **24.19.0** (see `.node-version`), npm, and uv **0.13.0**.
Install tools using their official instructions linked in the [development guide](docs/development.md).
From the repository root:

```sh
make setup
make verify
```

In two terminals:

```sh
make api  # http://127.0.0.1:8000/health — process liveness only
make web  # http://127.0.0.1:5173 — preparation page only
```

No GPU, account credentials, database, or client footage is required for these checks.
An optional PostgreSQL development service is defined in `compose.yaml`; the database schema
and migrations are the **planned first task**, not part of this preparation scaffold.

## Existing model work

Code for training and testing models already exists in
[playonsportsresearch](https://github.com/mnshah0101/playonsportsresearch).
That is a separate research repository. Connecting its model results to this app still needs
work; see [how the research connects to the app](docs/ml-integration.md).
Do not copy client data, labels, predictions, saved models or private reports into this repository.

## Submission

Submit [the repository URL](https://github.com/mnshah0101/6313-StreamSense) on Canvas,
one link per team. The documents and starter setup are on the main branch.
See the review record for the team's acceptance and the verification record for actual checks.
Open decisions remain documented; no feature implementation or production readiness is claimed.

AI assistance was used to inspect source materials and repositories, draft documentation,
prepare the starter setup, and propose the first task's plan. Team acceptance is recorded from
Chang's confirmation. The team owns the final decisions and remains responsible for correcting
errors and explaining the work during the Go/No-Go Review.
