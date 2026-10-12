# Team review and submission readiness

**Status: accepted for the readiness submission. Implementation has not started.**

On October 11, 2026, Chang confirmed that Moksh, Thomas and Chang had reviewed and agreed to
the project decisions and proposed plan. This records Chang's confirmation of the team's review;
it does not claim a new meeting took place or that each person separately ran the software.
Instructor approval to begin implementation remains pending for the Go/No-Go Review.

## Review outcome

| Item | Recorded outcome |
| --- | --- |
| Team members covered by the confirmation | Moksh Shah, Thomas Li, Rui Chang Lyu (Chang) |
| Confirmation recorded | October 11, 2026, through Chang |
| First task | TASK-001: Account, ModelVersion, MediaAsset and AnalysisJob database tables |
| Plan verdict | Accept the proposed task and plan as written for this submission |
| Requested changes | No further technical changes requested; simpler wording was requested and applied |
| Responsibility | Parallax team; choose the individual implementation lead before work begins |
| Implementation | Not started; awaiting instructor go/no-go |

## Why the accepted plan fits the project

The following summarizes the reasoning and limits in the accepted task and plan; it is not
a transcript or a quotation from individual teammates.

- **Useful first step:** users, uploaded files, model versions and jobs provide records needed
  by later login, upload and analysis features. This follows the detailed design and iteration plan.
- **Clear scope:** the task creates only four tables and their setup scripts. It does not claim
  to build login, video analysis, review screens or the background worker.
- **Checkable results:** the proposed tests cover valid records, duplicates, missing links,
  invalid values, required fields, safe repeat setup and undoing setup on a disposable database.
- **Important limits:** storing permissions does not enforce access. Blocking linked-record
  deletion is a starting rule, not the final retention policy. Model results still need a tested
  translation into the app's format.
- **Questions left for later features:** login provider/access rules, hosted services, upload
  limits, worker retries and demo timing remain listed in the decision document. They must be
  settled before those features are built; they are not delegated to the agent to guess.

The team accepts this bounded first task. Acceptance for the readiness submission is separate
from instructor permission to implement it or client approval of hosting and data use.

The [review guide](review-guide.md) adds plain-language explanations, concrete future test
examples and a rubric evidence map. It is preparation support, not a new team-review transcript.

## Points to explain during the Go/No-Go Review

Each member should be ready to explain:

- Why model analysis runs separately from web requests and how results reach the timeline.
- How a review links back to the exact model result, frame, job and uploaded file.
- Why reviews do not replace the model's original result.
- Why an image-level severity rating cannot stand in for validated per-defect severity.
- Why settings are chosen on validation data and the final test set stays separate.
- What exists now, what the prototype illustrates and what still needs implementation.
- How to run the starter setup and checks, and what those checks do not prove.
- Where the agent finds the specifications and which decisions require team input.

## Submission evidence

- [x] Team agreement and acceptance of the plan recorded through Chang's confirmation.
- [x] Specifications, AGENTS.md, first task and agent plan are linked from the README.
- [x] Local starter checks and GitHub automated checks passed; see the verification record.
- [x] Database/GPU/hosting checks that were not run are disclosed.
- [x] Original client data, source PDFs, private recordings and credentials are excluded.
- [x] Preparation materials are in the main repository; AI assistance is disclosed.
- [x] The proposed database task remains unimplemented.

An independent setup run by each teammate has not been recorded. Important later design
questions remain in `../decisions.md`; their presence is a readiness limitation, not a claim
that the entire application is ready to implement without further decisions.

Submit one repository link for the team:
https://github.com/mnshah0101/6313-StreamSense
