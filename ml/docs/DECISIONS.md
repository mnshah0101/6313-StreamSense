# Stage 1 decisions and review boundaries

This document reconciles ambiguities in `prompt.md`. All client label interpretations
remain provisional; inspection does not alter the source archive or labels.

## Current scope

Implemented: structured configuration, read-only label inspection, reproducible local
run records, a shared adapter contract/registry, generated synthetic fixtures, tests,
and a staged-data commit guard. Only the default CPU environment has been exercised.
No trained model, image corruption audit, perceptual-hash comparison, split, metric,
or performance result is claimed at this checkpoint.

The layout is rooted in this repository rather than an additional outer `streamsense/`
directory. The Python package is `streamsense/`; configurations are in `conf/`.
Later modules are added when their delivery stage is implemented, rather than filled
with no-op functions or tests that skip unfinished behavior.

## Data and privacy

- The zip wrapper is a config field, `data.root_subdir=partition_1`. Auto-detection
  examines only that root's immediate JSON files and fails on zero/multiple candidates.
- Inspection reads the archive in place. Extraction, checksums used to reuse extracted
  data, full image loading, duplicate detection, and manifests belong to stage 2.
- `decision`, `source`, `term`, and `updated_at` are required. `description` and
  `severity` are optional. Unknown fields are preserved in the source and flagged
  fatal by default; `labels.unknown_fields=preserve` explicitly permits them. Stage 2
  will put their values in the manifest's `extra` column.
- Out-of-range, boolean, null, fractional, or string severity values are invalid.
  A missing severity field is allowed on positive rows. Missing and JSON null are
  distinct in the **input** schema; `null` is available in the prediction contract.
- Empty positive terms and negative rows carrying annotations are fatal by default
  because silently accepting them would change label semantics.
- Inspection reports raw counts, including duplicates. Policy-based row filtering,
  loss weighting, and severity imputation are deferred to ingestion/training.
- Generated `docs/DATA_SCHEMA.md` and run artifacts are local and ignored. No client
  descriptions, game keys, or example labels are copied into tracked docs.
- Tests generate synthetic images and label JSON at runtime. They do not bypass the
  pre-commit prohibition on staged images or labels.

## Taxonomy and model outputs

- Provisional mapping includes `oversaturation -> white_balance_saturation` and
  `motion blur -> blur_lens_smear`; all mapping entries remain `confirmed: false`.
  `low contrast` retains a distinct raw term and provisionally maps to `other`.
- Aliases cover observed formatting variants. Other new terms are reported for review;
  the inspector does not fit the train vocabulary or silently amend taxonomy files.
- Crew-class ground truth is mapped **before** rare-term folding, so rare weather
  labels do not vanish from crew-class support. The train-only vocabulary and model
  score aggregation must explicitly account for rare terms at stage 2/3.
- `confidence` means probability that an issue exists, not confidence in whichever
  label won. It is nullable when a model does not supply a score. VLM self-reported
  scores must be marked as such; they are not assumed calibrated.
- Per-term/crew scores live in a private sidecar keyed by manifest key, keeping the
  public output field names unchanged. Missing scores are absent, never made-up zeros.
- A no-issue prediction has `issues=[]` and `severity=null`. Severity may also be
  null when unavailable. True positive rows missing severity contribute no severity
  loss or metrics. LoRA must mask unknown severity value tokens as well as prompt and
  image tokens, rather than invent numeric targets (stage 5).
- Metadata is populated by the runner. Descriptions may supply output explanations
  but never become image-model inputs by default.

## Evaluation and reproducibility

- One objective everywhere: maximize recall subject to the selected precision target.
  An unattainable target must be reported explicitly, not represented as a successful
  operating point with zero predictions.
- During development, use validation for checkpoint/prompt/threshold selection and
  reports. Final test evaluation requires `eval.split=test eval.final_test=true` and,
  once implemented, the locked test manifest. Never fit transforms on test.
- The seed in the split config interpolates the one top-level seed; divergence fails
  validation. Vocabulary fitting and future imputation use train only.
- Stage 2 will group games connected by cross-game duplicate pairs before assignment,
  keeping both whole games and identified duplicates on one side of each split.
  A duplicate threshold is configurable; possible false matches must be auditable.
- The adapter boundary is model-agnostic, but adapters own their training strategy:
  logistic fitting, supervised multi-head losses, and autoregressive SFT differ.
  Shared metric calculation is introduced once in stage 3.
- Default BF16 training settings mean "use where supported"; CPU behavior and GPU
  capability fallback are verified when training is implemented.
- Immutable model revisions and a resolved dependency lock are present. Package
  resolution is not proof of model-loader or CUDA compatibility; those get smoke tests
  at their implementation stages. Serving has a separate environment because its
  pinned dependency constraints differ from the HF training stack.
- Config hash, resolved config, source hashes, git state, seed, package versions,
  timestamps, completion status, and wall time are recorded for inspection runs.
  Fields requiring a loaded model/GPU remain null; no hardware is inferred from a
  config name. Run directory suffixes are unique tokens; config hashes live in records.

## Deferred scope

Stage 3 completes the actual E-00 tiny-CNN/parser/evaluation smoke. Stage 4 verifies
AutoProcessor and AutoModelForImageTextToText against the locked Transformers version,
with an explicit smoke-only Qwen2.5-VL fallback if loading fails.
Stage 5 verifies LoRA targets against named language modules, freezes the vision tower,
and treats projector training separately; matching module-name suffixes alone is not
enough to protect the vision encoder.

Quantization (AWQ/GPTQ), distillation, heat maps, conditional inference between frames,
flexible-name experiments, and a web app remain TODOs. No placeholder reports claim
that these experiments have run.

## Stages 2-4 decisions (2026-09-23)

- Label policies (`severity_missing=drop_row`, `source_filter=user_only`) apply to training
  rows only. The manifest, split and every evaluation always use all usable images, so the
  locked test set does not depend on training policy.
- The split searches seeded random game orderings (`split.n_trials`) and keeps the most
  balanced one. A coverage penalty keeps every crew class with 3+ games in all three splits.
  Weather appears in only two games, so it cannot have test support.
- The lock was regenerated once, before any model had been run, to add that coverage
  penalty. It must not be regenerated again.
- Pixel-level corruption and perceptual-hash near-duplicate checks were skipped by decision.
  Identical files are still detected by SHA-256 and grouped before splitting (0 found).
- Operating points are fit on val and applied to the eval split. On val itself they are
  marked optimistic. Unattainable targets are reported as unattainable.
- The level-1 term vocabulary is fit on train (`min_term_count`); rarer terms fold to other.
  Crew-class ground truth maps raw terms before folding.
- VLM score: the answer is forced to begin with `{"quality_issue":`. At that first step the
  adapter records P(true)/(P(true)+P(false)) from the unconstrained distribution, then allows
  only true/false. The rest of the JSON is generated freely and parsed. The self-reported
  `confidence` stays in the output but is not the score. Without this constraint, Qwen3.5-0.8B
  wrote defect names as the `quality_issue` value (8/8 parse failures on a probe).
- VLM frames are resized to a 896 px long side before the processor (config
  `model.image_max_side`) to bound visual tokens.

## Stage 5 (LoRA) decisions (2026-09-23)

- LoRA targets are resolved to full module names under `train.lora.language_scope`
  (`model.language_model`). Leaf names alone would also hit Qwen2.5-VL's vision MLP
  (`gate/up/down_proj`). The adapter asserts no vision parameter is trainable. Qwen3.5's 18
  linear-attention layers use `in_proj_qkv`, `in_proj_z`, `out_proj`; with those listed,
  LoRA covers all 24 language layers (150 modules, 10.2M trainable parameters).
- SFT target: the answer after the forced `{"quality_issue":` prefix, in the output contract
  (terms folded to the train vocabulary; explanation from the description when present, else
  a template). The prompt and image tokens are masked. Unknown severities are written as
  `null`, and those tokens are masked.
- Decision-token loss: plain token-averaged CE barely trained the true/false token (1 of ~50
  answer tokens). Train P(true) was 0.175 for positives vs 0.156 for negatives. The loss adds
  `train.decision_loss_weight` x CE of that token (default 1.0; 0 reproduces plain SFT).
  Val AP went from 0.776 to 0.803, and recall at P>=0.90 from 0.37 to 0.44 (r=16, lr=1e-4).
- Scores: P(true) is computed from fp32 projections of the final hidden state onto the
  true/false token rows. bf16 logits collapsed scores onto a few values (e.g. exactly
  1/(1+e)): 129 vs 183 distinct scores on 184 val frames. `predict()` reuses this score and
  forces the matching first token, so the checkpoint-selection metric equals the reported one.
- Speed (Qwen3.5-0.8B, MIG 2g.48gb): flash-linear-attention kernels, answer-only logits with
  left padding, batch 8 without gradient checkpointing, and score-only val checks.
  Training went from 1066 to 90 ms/example. The answer-only loss equals the full-logit loss to
  1e-6 (fp32 check). causal-conv1d is not installed (no matching nvcc), so its
  PyTorch fallback is used.
- Memory: processor outputs are built per batch. Precomputing all pixel tensors (~11 MB each)
  exceeded the 16 GB job allocation (cgroup OOM kill).
- Grid points run as separate processes from `scripts/grid_overrides.py` (one line per Slurm
  array index), not in one Hydra multirun process.
- LoRA alpha is fixed at 32 across ranks, so alpha/r (the effective adapter scale) changes with rank.
- Early stopping: patience 6 checks x 25 steps. Recall at P>=0.90 on 86 val positives moves by
  several points per frame, and patience 3 stopped runs while AP was still improving.
- Split seed is decoupled from the training seed (changed 2026-09-24): `split.seed` is fixed at
  42, the seed that produced the locked test set. Previously it interpolated `${seed}`, so a
  seed rerun would have silently produced a different train/val split and mixed data variance
  into training-seed variance. The top-level `seed` now controls training randomness only.
