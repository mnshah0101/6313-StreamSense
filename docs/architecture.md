# Application architecture

## Scope and status

The planned application lets authorized users upload images/clips/matches, request analysis,
inspect progressively available frame results, and confirm or dismiss quality alerts.
The October 9 demo direction adds concurrent uploaded videos presented as simulated streams.
This does not authorize connection to PlayOn production streams or automatic stream shutdown.
Existing ML experiments live in the separate research repository; this app is a new scaffold.

## Components

| Component | Technology / responsibility | Boundary |
| --- | --- | --- |
| Browser | React + TypeScript; upload, jobs, timeline, alert review, metrics | No database/storage secrets; no trusted identity or model decisions from browser input |
| Application API | Python FastAPI; authentication, authorization, upload permission, jobs, reviews | Short requests; never decodes videos or loads GPU models inside a request |
| Analysis worker | Separate Python GPU process; claim job, decode, sample, batch inference, save results | Private database/storage access; no public inference endpoint required |
| Application database | PostgreSQL; metadata, relationships, job/review state and provenance | No image/video/checkpoint bytes |
| Media storage | Private Vercel Blob proposed in Detailed Design V1 | Authorized access only; object keys stay behind server-side access checks |
| Identity | Managed OIDC; invitation/account provisioning by webmasters | Provider and session implementation not yet selected |
| Model registry | Private manifests and checkpoints reachable by worker | Exact revision/checksum/configuration recorded per job |
| Offline research | Existing PyTorch/Hugging Face/Hydra pipeline | Independent environment and immutable split; no automatic ingestion of app feedback |

The design proposes Vercel for web/API and managed PostgreSQL, with separate client-provided
GPU compute. PACE is an existing experimentation environment. EC2 appears as a possible
future host in S2, not a provisioned service. Network connectivity, provider choices, costs,
private media delivery and deployment limits must be validated before deployment (D-03).
The local scaffold makes no claim that these hosted services work together yet.

## Analysis lifecycle

1. Authenticate the account; authorize its upload/analysis permission and asset access.
2. Issue an authorized direct-to-private-storage upload. Verify metadata and actual decoded format.
3. Persist an `AnalysisJob` bound to one asset, a fixed model and configuration; return HTTP 202.
4. Worker atomically claims a queued job with a lease. Decode and sample approximately every
   5,000 ms, then call the adapter in batches. Preserve timestamps in the original video clock.
5. Persist each successful frame result and its provenance as processing proceeds. The client
   reads paginated frame results and job status; progress must not wait for the entire match.
6. Record terminal success/failure/cancellation. A failed inference is never a clean frame.

Job states from S2: `queued`, `running`, `succeeded`, `failed`, `cancelled`.
Planned transitions: queued → running/cancelled; running → succeeded/failed/cancelled.
Lease expiry and bounded retries need the worker design in D-07; do not invent unlimited retries.
The first task stores these states but does not implement workers or transitions.

## Review lifecycle

An alert points to the original prediction and the immutable threshold/policy version that
raised it. A review transaction checks authorization and the expected alert version, saves
one decision with reviewer/time, and updates status atomically. Conflicting or stale writes
return 409. Original model output is unchanged. Confirm means reviewed as a real issue;
it does not mean a crew was notified. Reviewed examples are not automatically training labels.

## Performance and demonstration

The <5 s target applies to a sampled frame on stated hardware, not an entire video or upload.
Benchmark decoding/preprocessing/inference separately and report end-to-end latency, batching,
memory and throughput. CPU scaffold checks cannot demonstrate L4 performance. The ~100-stream
figure in the September 18 summary is provisional because S4 describes 100–120 as a reference
measurement rather than a fixed acceptance target. See D-04 for the remaining decision.

The final demo should show multiple video jobs with growing timelines. Number of simultaneous
videos, playback pacing, update transport, and timing acceptance criteria remain to be agreed
before that feature is implemented (D-08). The existing prototype shows a completed single-match view.

## Exclusions

No production stream ingestion, live Slack/crew routing, automatic shutdown, game-state detection,
payments, multi-client tenancy, temporal model requirement, or automatic retraining from reviews.
Heat maps, routing between models, and frame-delta optimization remain optional experiments.
