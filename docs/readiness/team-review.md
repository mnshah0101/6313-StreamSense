# Team review and Go/No-Go preparation

**Status: pending.** This worksheet is intentionally incomplete until the team reviews the work.
Prepared materials and agent commentary do not establish team understanding or approval.

## Review the first task and plan together

Read `../tasks/001-database-foundation.md` and `../tasks/001-agent-plan.md`, then answer in your own words:

1. Do we want to build these four database tables first? Why?
2. Does the plan match our design and database diagrams? Which rules are missing or wrong?
3. Do we agree on how IDs, timestamps and permissions are stored, and on blocking deletion of records that other records need?
4. Do the planned tests show that each completion requirement is met? Which failure case should be added?
5. Which questions can wait, and which need answers before this task starts?
6. What would we change in the agent's plan? Record concrete corrections, or explain why none are needed.

| Required record | Team entry |
| --- | --- |
| Review date / participants | Pending |
| Task owner | Pending |
| Plan verdict: accept / revise / replace | Pending |
| Reasons and requested corrections | Pending |
| Corrections applied and checked by | Pending |
| Instructor implementation approval/date | Pending |

The agent's critique in the plan is provided for discussion. Do not relabel it as the team's feedback.

## What each team member should be able to explain

Each member should be able to explain the following without reading an AI-generated script:

- Why model analysis runs separately from web requests and how results reach the timeline as they arrive.
- How a review links back through its alert and model result to the exact frame, job and uploaded file.
- Why model output and human review are stored separately.
- Why one severity rating for an image cannot be treated as a tested rating for each defect.
- Why settings are chosen using validation data, while final test data is kept separate.
- What the prototype demonstrates versus what remains unimplemented, especially multiple videos.
- How to install/run/check the repository, and which external-service checks remain unverified.
- Where the agent finds specifications and when it must stop for a decision.

| Member | Documents/plan reviewed | Can explain design and limitations | Notes/corrections |
| --- | --- | --- | --- |
| Moksh Shah | Pending | Pending | Pending |
| Thomas Li | Pending | Pending | Pending |
| Rui Chang Lyu (Chang) | Pending | Pending | Pending |

## Before submitting the repository URL

- [ ] All members reviewed and corrected the specifications and proposed first-task plan.
- [ ] Source conflicts and important unresolved decisions have been discussed and assigned.
- [ ] Local setup/checks were reproduced by a team member; hosted CI status was checked.
- [ ] Missing database/GPU/hosting evidence is accurately disclosed, not marked as passed.
- [ ] No private client artifacts, source PDFs, credentials or meeting recordings are tracked.
- [ ] The readiness PR is merged and the repository root links to all assignment materials.
- [ ] AI use is disclosed accurately and no feature implementation was done before approval.

Submission: `https://github.com/mnshah0101/6313-StreamSense` — one link per team.
