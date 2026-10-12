# What the database will store

Source: Detailed Design V1 §§3.2–3.8 and Figures 4–5. The tables below are planned, not built.
They connect users, files, analysis requests and results.

How to read the tables: `PK` identifies a record; `FK` links it to another table. `UUID` is the
ID format. `UNIQUE` means two records cannot share that value. `?` means a field may be empty;
other fields are required unless stated otherwise. Times use UTC with timezone information.
Keep video files, passwords, login-provider tokens and saved models outside these records.

## Four tables for the first task

| Table | Fields |
| --- | --- |
| Account | `account_id UUID PK`, `subject text UNIQUE`, `display_name text?`, `email text?`, `role text`, `permissions JSONB`, `active boolean`, `created_at timestamptz` |
| ModelVersion | `model_id UUID PK`, `provider text`, `checkpoint_key text`, `revision text`, `manifest_key text`, `checksum text`, `adapter_version text`, `output_schema_version text`, `prompt_hash text`, `scoring_method text`, `created_at timestamptz` |
| MediaAsset | `asset_id UUID PK`, `owner_id UUID FK Account`, `game_key text?`, `object_key text UNIQUE`, `mime_type text`, `sha256 text`, `retained_until timestamptz?`, `created_at timestamptz` |
| AnalysisJob | `job_id UUID PK`, `asset_id UUID FK MediaAsset`, `requested_by UUID FK Account`, `model_id UUID FK ModelVersion`, `status text`, `sample_interval_ms integer`, `config_hash text`, `lease_expires_at timestamptz?`, `failure_code text?`, `created_at timestamptz` |

One account can own many uploaded files and request many analysis jobs. Each job has exactly one asset,
requesting account and fixed model version. Assets may have many jobs. A model may be reused
by many jobs. `Account.role` is `webmaster` or `regular`; job states are the five states in
`architecture.md`. `permissions` must be a JSON object; the exact permission names and
how file access is granted will be decided in the access-control task (D-02).

The database must reject missing links, duplicate account subjects/file keys, nonpositive
sampling intervals and invalid roles or job states. Add indexes—a way to speed up lookups—for
jobs by `(status, created_at)` and assets by `(owner_id, created_at)`.

For the first task, propose explicit IDs/timestamps and block deletion of a record while other
records depend on it. Do not automatically create accounts, assign default roles, delete linked
records or add real model records. The team must review these choices. Later deletion work must
also remove files and handle anonymous audit records (D-06).

## Tables for later tasks

| Table | Fields / relationships |
| --- | --- |
| SampledFrame | `frame_id PK`, `job_id FK`, `timestamp_ms bigint`, `object_key text`; UNIQUE `(job_id, timestamp_ms)` |
| Prediction | `prediction_id PK`, `frame_id FK UNIQUE`, `schema_version text`, `quality_issue boolean`, `issue_score float?`, `raw_output JSONB`, `latency_ms integer` |
| Defect | `defect_id PK`, `prediction_id FK`, `name text`, `description text?`, `severity smallint?`, `severity_source text`, `location_text text?` |
| LocalizationArtifact | `localization_id PK`, `defect_id FK`, `model_id FK`, `method_name text`, `method_version text`, `method_status text`, `object_key text?`, `region_bounds real[4]?`, `frame_width integer`, `frame_height integer`, `checksum text?`, `is_current boolean`, `created_at timestamptz` |
| Alert | `alert_id PK`, `prediction_id FK UNIQUE`, `threshold_id FK`, `review_status text`, `version integer`, `created_at timestamptz` |
| ReviewDecision | `decision_id PK`, `alert_id FK UNIQUE`, `reviewer_id FK Account`, `decision text`, `reviewed_at timestamptz`, `note text?` |
| AuditEvent | `event_id PK`, `actor_id FK Account`, `action text`, `resource_id UUID`, `occurred_at timestamptz` |
| DatasetSplit | `split_id PK`, `manifest_key text`, `manifest_sha256 text`, `split_unit text (= game_id)`, `seed integer` |
| EvaluationRun | `run_id PK`, `model_id FK`, `split_id FK`, `config_key text`, `metrics_key text`, `seed integer`, `hardware text`, `started_at timestamptz` |
| ThresholdVersion | `threshold_id PK`, `model_id FK`, `calibration_run_id FK EvaluationRun`, `created_by FK Account`, `issue_score_cutoff float`, `severity_cutoff smallint?`, `created_at timestamptz` |

`Defect.description` is a **proposed addition** to match the written model-output requirement;
Figure 4 has `name` and `location_text` but no description column. Confirm before that migration.
The written design also needs records for login sessions, file access, upload checks, retries,
model settings, repeated requests and failed frames. Its database diagrams do not fully describe
these yet. Resolve D-02/D-05/D-07/D-09 before building the affected features.
Do not imply those records already exist or silently add them to TASK-001.

## Rules that keep later records consistent

- A frame has zero or one prediction while processing; each successfully processed frame has
  exactly one. Failed frames need an explicit failure record (D-07), not a clean prediction.
- One prediction has zero or more defects and at most one alert. An open alert has no decision;
  a reviewed alert has exactly one. Confirmation/dismissal never overwrites the prediction.
- Review decision is `confirm` or `dismiss`. Alert review states are `open`, `confirmed`,
  `dismissed`. Decision creation and status/version change share a transaction.
- Severity, when validated and present, is integer 1–5. Unknown is null with
  `severity_source=unavailable`; validated model output uses `severity_source=model`.
- Scores/cutoffs are in [0,1]; latency and frame timestamps are nonnegative.
- Threshold versions are immutable, model-specific and calibrated on validation. Reject a
  calibration run for a different model; never tune with final test data.
- Store split identity and evaluation subset distinctly. The diagram lacks an explicit subset
  field; the evaluation migration must add a reviewed representation so val/test cannot mix (D-09).
- Localization status is `available`, `unsupported`, or `failed`. Only available artifacts
  have viewable files. Validate dimensions and coordinate bounds before rendering.
- Localization coordinate convention and one-current-overlay uniqueness need a concrete
  contract before the localization task (D-09). Attention magnitude alone is not validated localization.
- Versioned inference settings must remain retrievable, not just hashed; S2 requires both.
- Index review queue `(review_status, created_at)` and frame lookup `(job_id, timestamp_ms)`.

## Privacy and deletion

Account details and footage references are private. The client must agree on how long data is
kept before real-data storage and deletion are built. An empty `retained_until` means no period
has been set; it does not mean footage can be kept forever. The team must also decide how to
keep anonymous audit records while handling links to deleted accounts. Do not assume that
deleting one record automatically deletes all connected records.
