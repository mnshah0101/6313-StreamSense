# User flows and acceptance boundaries

Derived from the task scenarios, Detailed Design V1 and the October 9 sync. All flows below
are planned. Login and permissions precede access to real data; the local scaffold does not
implement these flows.

## 1. Analyze an image or clip

Authorized user → choose file → validate upload → private upload → create analysis job →
queued/running progress → incremental frame results → terminal result/failure.
The Run action is unavailable without a valid selection. Duplicate submissions must not create
duplicate jobs. Upload success alone is not analysis success. Model or parsing errors are
visible failures, not a “good” result. File limits await D-05.

## 2. Inspect a match / simulated streams

Choose uploaded match(es) → create jobs → follow growing timelines → select a timestamped
marker → inspect the exact stored frame/prediction → review source/model/run details.
One job's results cannot appear under another video. Partial results stay distinguishable from
a completed analysis. Sampling uses the source media clock. Multiple-video pacing and update
mechanism await D-08; prototype final metrics are not acceptance evidence.

## 3. Confirm a real issue or dismiss a false alarm

Open authorized queue → inspect frame and defects → Confirm/Dismiss → save review atomically
→ move out of Open → show saved status in Reviewed.
The reviewer identity comes from the session. A stale version returns a conflict requiring a
refresh; a failed save retains the prior state and offers a retry. Confirmation does not send
notifications. Original model output remains accessible alongside the review record.

## 4. Inspect localization

Open frame detail → if a validated spatial overlay exists, toggle it on → inspect region text
and original image → toggle off. A missing overlay has an explicit unavailable state; global
defects do not get a misleading localized region. This is gated on model-localization validation.

## 5. Inspect metrics and publish thresholds

Authorized engineer → select recorded model/run/split → read binary/per-defect metrics and
support → preview threshold tradeoffs from validation → webmaster publishes a new version.
Historical results keep their original policy. Unknown per-defect severity disables the severity
cutoff. No threshold selection uses final-test metrics. Identity and threshold publication details
must be settled before this task.

## Readiness verification versus feature acceptance

`make verify` proves only that the preparation scaffold installs, lints, builds and passes its
small API boundary tests. These user flows need feature-level tests and team/client validation
later; do not mark them complete because the scaffold checks pass.
