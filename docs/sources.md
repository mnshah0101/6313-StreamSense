# Source basis and requirement traceability

## Source register

Source documents were supplied by Chang. Their private originals, signatures, meeting recordings,
contact details, and client assets are not copied into this public repository. Team members should
retain access to the originals for the Go/No-Go Review.

| ID | Source | How used |
| --- | --- | --- |
| S1 | Development Readiness Preparation assignment and 50-point rubric | Required artifacts, verification, plan-only first task, team ownership |
| S2 | StreamSenseFinalParallax.pdf, Detailed Design V1, October 4, 2026 | Sections 2–3: application architecture, schema, interfaces, security, and nullable severity |
| S3 | Iteration Plan.pdf | Global Setup & Infrastructure, feature stories, dependencies, and acceptance criteria |
| S4 | Updated_User_research.docx.pdf | Requirements R-01 through R-19 and distinction between requirements and interface ideas |
| S5 | StreamSense_MLP_Task_Scenarios.pdf and linked Figma prototype | Review, upload, timeline, localization, and calibration interactions |
| S6 | Parallax_Client_Charter.pdf and 6313-TeamCharter.pdf | Project scope, team responsibilities, review, and disclosure expectations |
| S7 | Week 3, Week 4, and Week 5 meeting/standup documents | Earlier decisions; Week 4 records AI tooling allowed and PACE access |
| S8 | September 18 client sync summary and supplied client-response screenshots | Precision priority, L4 class hardware, frame latency, VAE context, optional localization |
| S9 | September 25 client sync summary | Model/data investigation, proposed experiments, reported binary precision and recall goals |
| S10 | October 9 client sync summary | Async inference, model-first client priority, course web demo, multiple-video timeline, instructor gate |
| S11 | Research repository at commit `22a39b63526a696595ee5eb42b9bc790514464b9` | Evidence of existing code and its interface; not proof of independently reproduced model results |
| S12 | Application repository at commit `d8a81704d775c029372526d3458799d4ce5e790d` | Starting state was a single README |

[Prototype](https://www.figma.com/proto/m22oT1kKlNysFpEaeVg8NJ/StreamSense-Mid-Fi-Prototype---Parallax-6313?node-id=12-3282)
was inspected through its shared browser view. The connector did not have edit access.
Main views inspected: alert queue, alert detail, heat-map toggle, upload, completed-match
timeline, and model performance. This was not an exhaustive test of every prototype branch.

## Precedence and interpretation

Use S2 for the planned application structure and S10 for the later demo clarification.
S4 preserves client requirements; S3 decomposes work. S5 is an interaction reference, not
proof of implementation or measured performance. Where these conflict, the decision register
records the distinction rather than silently declaring a new requirement approved.
Meeting summaries can compress or misattribute technical statements. Treat numerical claims
and proposed experiments as dated reports until supported by a run record or team confirmation.

## Requirements mapped to specifications

| Requirement | Source | Specification / evidence needed |
| --- | --- | --- |
| Binary issue/no-issue result; multiple named defects (R-01–04) | S4, S8 | `api.md`, `ml-integration.md`; schema and known-frame tests |
| Descriptive/localized defects (R-05) | S4, S8 | Optional localization in `design/ui-spec.md`; validated method required |
| Per-defect severity and alert policy (R-06) | S4, S2 §3.7 | `data-model.md`; unavailable until per-defect validation, no invented ratings |
| Precision first; report precision, recall, F1 and per-issue results (R-07–08) | S4, S9 | `ml-integration.md`; report actual split, support and operating point |
| Under 5 seconds per sampled frame, roughly 5-second sampling; L4 class GPU (R-09–11) | S4, S8 | `architecture.md`; measured hardware-labelled benchmark, no full-match 5-second promise |
| Web testing for a clip or whole match (R-12) | S4, S6, S10 | Upload and progressively updating timelines in `design/` |
| Training details, metrics and visualizations (R-13) | S4 | Immutable run/model provenance in `data-model.md` |
| Flexible defect names (R-14) | S4, S8 | Text defect names with separate evaluation mapping in `ml-integration.md` |
| Game-level split; duplicate/missing-file handling (R-15–16) | S4 | Research ingestion and locked split; do not change during app integration |
| Weather remains an issue; metadata research (R-17–18) | S4 | Preserve weather context; external metadata integration remains research |
| IQA scope, no game-state duplication (R-19) | S4, S6 | Scope exclusions in `architecture.md` |
| Async jobs and multiple-video demo | S10 | Job lifecycle and incremental frame results; extension beyond completed-match prototype |
| Team reviews plan before implementation | S1, S10 | `tasks/001-agent-plan.md`, `readiness/team-review.md` |

The September 25 summary reports a goal of at least 90% binary precision and recall.
Earlier materials describe 90%+ binary performance with precision emphasized. Preserve the
stronger goal as a reported aspiration; precise acceptance protocol, recall floor, dataset
version and confidence reporting still need agreement (D-04). Neither meeting figures nor
prototype dashboard numbers establish a current pass.
