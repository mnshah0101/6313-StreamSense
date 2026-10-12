# Decision register

The source-based draft separates recorded direction from choices that remain open. Suggested
owners below are review roles, not assigned commitments or evidence of approval.

## Recorded direction

| Topic | Current basis |
| --- | --- |
| Main repository | Chang selected `6313-StreamSense`; research remains linked separately |
| Frameworks/storage | S2 proposes React/TypeScript, FastAPI, PostgreSQL, private Blob and a separate Python GPU worker |
| Async analysis | S2 and S10 agree on returning a job immediately and processing separately |
| Demo scope | Upload-based analysis, extended by S10 to multiple videos and growing timelines |
| Human review | Confirm/dismiss with provenance; no external crew delivery or stream shutdown |
| Data quality | Whole-image severity does not establish per-defect severity; unavailable remains null |
| Agentic work | S7 records AI tooling allowed; S1 requires team review and plan-only first task |
| Preparation tooling | Vite scaffold, uv/npm locks, pytest/Ruff/Oxlint/TypeScript checks; proposed routine setup choices for team review |

## Open decisions and implementation gates

| ID | Decision needed | Blocks | Who should resolve |
| --- | --- | --- | --- |
| D-01 | Confirm the drafted scope/specifications and first task; record instructor go/no-go | Feature implementation | All team members / instructor |
| D-02 | OIDC provider, session store/lifetime, invitation flow, permission vocabulary and asset-grant schema | Authentication and private data routes | Team; client for hosted access |
| D-03 | Actual GPU host, managed DB provider/network access, Vercel/private-media feasibility, credentials and cost approval | Deployment and real-media demo | Team and Vijay |
| D-04 | Binary precision/recall acceptance protocol, dataset version, latency statistic/batch/load, whether ~100 streams is a goal or reference | Model performance acceptance | Team and Vijay |
| D-05 | Allowed codecs/formats including MOV, upload bytes/duration limits, upload finalization/validation state | Upload implementation | Team and client usage input |
| D-06 | Retention/backup periods, deletion and audit anonymization/FK behavior | Real-data ingestion and deletion | Team and Vijay |
| D-07 | Lease duration, retry/backoff and cancellation behavior, failed-frame representation, incremental pagination and idempotency | Worker/job API | Team |
| D-08 | Demo video count, playback pacing, update transport and UI timing acceptance | Multiple-video timeline implementation | Team; confirm demo expectations |
| D-09 | Reconcile schema gaps: defect description, evaluation subset, retrievable config, overlay coordinates/current version | Corresponding later migrations | Team |
| D-10 | Selected checkpoint, app adapter contract, validated scoring/severity/localization evidence | Model promotion into app | Team / model lead, with client review |

TASK-001 deliberately has no dependency on provider selection, client media, performance results
or worker scheduling. It is limited to four core tables and local migration tests. Its proposed
restrictive deletion policy and explicit values are reviewable in the task/plan, not hidden defaults.

## Reconciled differences

- S7's PACE and “EC2 unavailable” reflect earlier experimentation; S2's possible EC2 host is
  a later hosting proposal. Neither proves future production resources are provisioned.
- S3/S5 describe possible crew routing; S2 excludes it. Document confirmation as review only.
- S5's completed single-match prototype remains useful, but S10 adds incremental multi-video demo work.
- S9 reports 90%+ precision and recall as a goal; S4 leaves recall acceptance open. Do not
  quietly change the objective or report it achieved.
- S8 mentions ~100 concurrent streams; S4 describes 100–120 as reference performance. Benchmark
  and agree acceptance instead of treating an approximate meeting summary as a load guarantee.
- The research repository has historical stage notes and newer decisions. Application integration
  uses the actual current interface and run provenance, not superseded stage-1 assumptions.

## Recording a resolution

For each decision, add date, exact decision, source/approver, affected specifications and any
verification required. Do not mark a decision approved on behalf of a teammate or client.
