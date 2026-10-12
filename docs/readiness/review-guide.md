# Review guide and evidence map

Use this guide to prepare for the course review. These are explanations to understand, not a
record that every teammate has already answered the questions. The instructor assigns the score.

## Where each rubric requirement is covered

| Rubric category | Points | Evidence to open | What the team should demonstrate |
| --- | --- | --- | --- |
| Project specifications | 15 | [Architecture](../architecture.md), [data](../data-model.md), [interfaces](../api.md), [security](../security.md), [screens](../design/ui-spec.md), [source map](../sources.md) | Explain the approved design, distinguish it from prototypes and proposals, and identify decisions that block later work. |
| Agent configuration | 10 | [AGENTS.md](../../AGENTS.md) | Show where the agent gets requirements, when it must ask, and how it verifies changes. |
| Development environment | 5 | [Setup instructions](../development.md), [actual results](verification.md), [CI workflow](../../.github/workflows/verify.yml) | Run the starter app and checks; explain which features are still absent. |
| First task and plan | 10 | [Task and acceptance criteria](../tasks/001-database-foundation.md), [agent plan](../tasks/001-agent-plan.md), [review record](team-review.md) | Explain why four tables come first, how tests prove completion, and why implementation has stopped. |
| Team understanding | 10 | The explanations and questions below | Each teammate can explain the decisions in their own words, including their limitations. |

## Explain the project in one minute

StreamSense checks uploaded sports footage for image-quality problems. The web app accepts
files and shows results. The API checks who may access a file and records an analysis job.
A separate worker runs the model so a long video does not keep a web request waiting.
PostgreSQL stores the people, files, model versions and job records. Private storage holds
the actual media. The screen shows results as they arrive, and a person can confirm or dismiss
an issue. That review is saved separately from the model's original prediction.

The client mainly needs the model. The class also needs the app and a demo using multiple
uploaded videos. The current repository contains preparation documents and a running starter
page/API, not the finished product. The first proposed task creates the four core database tables
after instructor approval.

## Questions everyone should be able to answer

| Question | Essential reasoning |
| --- | --- |
| Why not run the model directly inside a web request? | Video analysis can take time. A saved background job lets the page remain responsive and lets the worker report progress. |
| Why these four tables first? | Each analysis needs an owner, an uploaded file and an exact model version. The job ties those records together; later features depend on them. |
| Why not use the research repository as the app? | It contains model experiments, not the app's users, access checks, job tracking and review screens. Its outputs need an explicit translation into the app's format. |
| How do we know which prediction someone reviewed? | The review must trace through the stored result and frame to the job, file and model/settings. A review does not overwrite the model's answer. |
| Does saving permissions protect a file? | No. Future API access checks must enforce permissions. The first database task only stores records. |
| Why can severity or a heat map be unavailable? | The model must actually support and validate those outputs. An image-level label is not proof of the severity or location of each defect. |
| Why keep a separate final test set? | Selecting settings using the final test set would make the reported performance less trustworthy. Choose settings on validation data. |
| What does a passing setup check prove? | Dependencies, basic API behavior, code checks and frontend build work. The separate PostgreSQL check proves connectivity and basic data types, not the planned schema, access controls or model quality. |
| What is the difference between team acceptance and instructor approval? | Team acceptance records review of the plan. Instructor go/no-go permits implementation. Neither proves client approval of hosting, costs or data use. |

## Critically examine the first plan

These examples make the existing acceptance criteria concrete. They are future tests, not
results already obtained or new claims about a team discussion.

| Concern to challenge | Example of evidence required after implementation |
| --- | --- |
| Can the four tables actually work together? | Save one made-up account, model, asset and job, then read the same IDs and links back. |
| Can broken data get saved? | Reject a job pointing to a missing asset, a zero sampling interval, a duplicate account subject and permissions that are a list instead of an object. |
| Are optional and required fields distinguished? | A nullable value remains null; a required value cannot be null. Empty-string rules must follow the field specification rather than be invented. |
| Can removing a parent silently damage the records? | Attempt to delete an account or model still referenced by another record and confirm the database blocks it. |
| Is setup repeatable? | Create the schema, repeat setup, undo it on a disposable database, and create it again. Never run this destructive check on client data. |
| Is the task becoming too large? | Review the final changes for exactly four application tables and their migration/tests. Login, uploads, model runs and review features belong to later tasks. |

Choosing database work first has a tradeoff: it enables record storage but does not immediately
produce a usable upload or analysis screen. That is acceptable for a shared foundation task.
Starting with login instead would expose unresolved access/provider decisions before this
already-defined foundation is complete. Future schema changes will still be needed for sessions,
worker coordination and later model/review records.

## Before pressing Submit

1. Open the main repository and follow the assignment links in its README.
2. Read the team review record and make sure it reflects what was actually agreed.
3. Check the latest verification evidence, including what has not been tested.
4. Read the decision list. New recommendations are not approved merely because they are written down.
5. Submit one repository link for the team. Be ready to explain these materials at the Go/No-Go Review.

More code cannot substitute for team understanding. No grade or independent teammate review is
claimed by this guide.
