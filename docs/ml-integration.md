# Research and application integration

## Existing research boundary

[playonsportsresearch](https://github.com/mnshah0101/playonsportsresearch) at
`22a39b63526a696595ee5eb42b9bc790514464b9` contains ingestion, game-level splitting,
classical/CNN/VLM adapters, LoRA training and evaluation code. Its README reports completed
research stages; those model results were not independently reproduced for this assignment.
The benchmark entry point was still deferred at inspection. Keep its dependencies separate
from this lightweight API environment; no Torch or model weights are needed for preparation.

Research `ModelAdapter` exposes `fit`, `predict`, `save`, and `load`; predictions include
`quality_issue`, `issues`, nullable severity/confidence and metadata, with separate score records.
The app design uses `defects`, `issue_score`, database IDs and video timestamps. These are not
the same contract: implement an explicit translation layer in a future integration task.

## Integration constraints

- Decode frames in the worker. Preserve source frame timestamp, asset/job identity and a fixed
  model/adapter/output-schema version. A filepath-only or browser-provided prediction is not trusted.
- Map research issue names and raw terms into flexible app defect descriptions; keep normalized
  evaluation categories separate. A crew-facing label is not itself a classification metric.
- Translate the validated numeric issue score from the score sidecar with its scoring method;
  do not treat free-text/self-reported confidence as calibrated probability.
- Reject malformed output. Keep failure separate from negative/clean output.
- Current source labels rate whole images. Keep app per-defect severity null/unavailable until
  validated against appropriate labels; copying one frame severity onto every defect is invalid.
- Score-based alerts can be reviewed while severity suppression is disabled. Thresholds must
  be versioned with model and validation evidence.
- Preserve missing localization as unavailable. An attention map or generated box is not proof
  of defect location. Heat maps require a separate feasibility/validation gate.

## Evaluation protocol

Split by game, keeping duplicate-connected games on the same side, and preserve the locked
final test set. Vocabulary fitting/training uses train; model/prompt/checkpoint/threshold
selection uses validation. Do not regenerate the split or silently relabel locked test rows
as part of app work. Review disputed labels in a separate versioned curation process; if test
data were used for exploratory diagnosis, disclose that and agree a fresh evaluation protocol.

Report binary precision, recall, F1, per-defect results, severity slices when meaningful,
class support, actual hardware, model revision, preprocessing, seed and split version. Describe
uncertainty and selection on validation. Final test is a separate, explicit final comparison.
The precision-first operating point and the reported 90%+ precision/recall goal need the
acceptance clarification in D-04. Never substitute prototype metrics for measured results.

September 25 suggestions (severity weighting, MLP head, structured-output training) are
experiments, not an approved replacement architecture. Its summary's description of the loss
and the research code may refer to different runs. Reconcile against the exact run config
before making claims. Ground-truth severity/descriptions are targets or analysis metadata,
not default inference inputs; feeding annotations unavailable in normal use would invalidate
the demonstration/evaluation.

## Promotion into the application

A future promotion record must identify checkpoint checksum, adapter version, inference config,
output schema, scoring method, validation results and chosen thresholds, memory/latency evidence,
and the data/privacy authorization for the demo. S2's initial Qwen candidates and the research
repository's later recommendations are not a confirmed production selection (D-10).
