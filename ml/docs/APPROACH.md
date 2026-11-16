# StreamSense: approach in one page

*Team Parallax (Georgia Tech) for PlayOn Sports · status 2026-09-25 · all numbers are validation; the test set is locked.*

**Problem.** PlayOn streams high-school sports from unattended panoramic cameras. When the picture degrades
(lens smear, fog, stitching seams, bad exposure), nobody notices until viewers complain. StreamSense flags
degraded frames so a crew can fix the camera. A false alarm can take a stream down, so the system is
**precision-first**: catch as many real issues as possible while keeping ≥ 90% of alerts genuine.
Deployment target: a mid-tier GPU (NVIDIA L4), under 5 s per frame.

**Dataset (V1).** 1,219 labelled 1920×1080 frames from 152 games (596 issue / 623 clean; 234 duplicate
rows dropped). **Split by game** so no stream appears in two splits: train 849 frames / 106 games,
val 184 / 22, test 186 / 24 (locked until one final comparison).

**Data dictionary** (one row per frame):

| field | meaning | how we use it |
| --- | --- | --- |
| `decision` | client label: `valid` (has an issue), `not` (clean), `duplicate` | → `quality_issue`; duplicates dropped |
| `quality_issue` | derived yes/no | **primary target** |
| `terms` | free-text defect names, 18 distinct (blur, stitching artifacts, glare, fog, …) | secondary target, each mapped to one of 8 crew classes (`blur_lens_smear`, `stitching_black_patch`, `weather`, …) |
| `severity` | 1–5, one value per frame (not per defect) | secondary target |
| `description` | optional free-text note | training explanation when present |
| `source` | `prefill` (57%) or `user` annotator (43%) | optional loss weighting |
| `game_id`, `frame_idx` | stream and frame position | group key for the split and for confidence intervals |
| `weather_related` | derived from the terms | output flag |

**Input → target.** Input: one frame resized to 896 px plus a fixed prompt listing the defect vocabulary.
Target: a JSON answer the model writes after a forced prefix `{"quality_issue":`, e.g.
` true, "issues": [{"name": "blur_lens_smear", "raw_term": "blur", "severity": 4, "weather_related": false}], "severity": 4, "explanation": "…"}`.
The **score** is P(issue): the probability of `true` vs `false` as the first answer token, computed in fp32.
It ranks frames, sets the alert threshold and gives a calibrated confidence. No text generation is needed.

**Loss** (per training frame, then averaged over the batch):
**L = mean cross-entropy over the answer tokens + λ · cross-entropy of the true/false token** (λ = 1).
The yes/no decision is 1 of ~50 answer tokens, so plain token-averaged cross-entropy barely trains it;
the extra term makes the decision weigh as much as the rest of the answer. Unknown severities are masked
out of the loss. Optimiser: AdamW, cosine schedule with 5% warmup, gradient clipping at 1.0.
**Checkpoint selection:** recall at ≥ 90% precision on validation (tie-break AP), with early stopping.

**How we measure.** Recall at ≥ 90% / 95% precision (headline), average precision (AP) and log-loss
(calibration). Confidence intervals resample whole games. One config varies by up to ±0.06 AP across
seeds, so comparisons use **multi-seed means** and differences under ~0.03 AP count as noise.

**Models and techniques** (val AP / issues caught at 90% precision):

| approach | result |
| --- | --- |
| Classical quality score (BRISQUE/NIQE) + logistic regression | 0.72 / 13% |
| Image classifier (ResNet-18), fine-tuned | 0.83 / 47% |
| Vision-language models, zero-shot (Qwen3.5-0.8B, Qwen2.5-VL-3B) | 0.64 – 0.76 / ≤ 34% |
| VLMs + LoRA: Qwen3.5 0.8B–9B, Qwen3-VL 2B–8B, InternVL3.5 2B/4B | 0.82 – 0.90 / up to 67% |

Tried on the VLMs: LoRA rank/α/layers/modules, learning rate, epochs, batch size (grid in progress),
vision-encoder LoRA, projector training, 1280 px input, class-balanced sampling, loss weight λ,
LoRA variants (DoRA, rsLoRA, LoHa, LoKr).

**What we learned.** (1) Fine-tuned VLMs beat classical metrics and the CNN; size helps up to ~4B,
then plateaus. (2) **Recommended: Qwen3-VL-4B + plain LoRA** (3 seeds: AP 0.892, 67% caught at
90% precision, best calibration). (3) Most knobs stay within seed noise; InternVL, class balancing,
LoHa/LoKr and rsLoRA are worse, so **the limit is data, not the model**. (4) At the alert threshold,
Qwen3-VL-4B catches ~89-96% of severity-4/5 issues vs ~20-60% of severity 1-3 (3-seed means); misses are mostly mild.

**Next.** More labelled frames · latency on an L4 · seed ensembles · heat maps of problem areas
(prototype works; needs location labels) · per-defect severity labels.
