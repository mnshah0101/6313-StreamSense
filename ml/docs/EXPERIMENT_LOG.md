# Experiment log (LoRA exploration)

Running notes; all metrics are **validation** (184 frames, 22 games, 86 positives). The
locked test set is untouched. AP = average precision; R@P90 = recall at precision ≥ 0.90 with
the threshold fit on val (optimistic). Full per-run tables:
`python scripts/summarize_grid.py 'report.experiments=[E-07b,E-07c]'`.

## Noise floor (2026-09-24)

Same config (0.8B, r=32, lr=2e-4), three fresh seeds:

| seed | AP | R@P90 | R@P95 |
| --- | --- | --- | --- |
| 0 | 0.816 | 0.430 | 0.419 |
| 1 | 0.840 | 0.442 | 0.395 |
| 2 | 0.874 | 0.593 | 0.547 |

Seed-to-seed spread is about ±0.03 AP and ±0.08 R@P90. Single-seed differences smaller than
that are noise. The seed-42 grid run (AP 0.862, R@P90 0.570) that selected this config sits
inside that range, so the grid "winner" was not a fluke, but it was not a clear winner either.

Reference points: ResNet-18 AP 0.829 / R@P90 0.465 (one run); Qwen2.5-VL-3B zero-shot AP 0.753.

## Environment note (2026-09-24 10:55)

Another user's training job (`akhan633`, PID 364124) is running on the **same MIG 2g.48gb
slice** as job 5922039. It is visible in `nvidia-smi --query-compute-apps` for our device, using
1.6–14 GB. This does not affect correctness, but it makes timings noisy, shares compute, and can
cause OOM for memory-heavy runs (1280 px, 2B/4B, vision LoRA). OOM failures are requeued. It is
worth reporting to PACE support, since MIG slices are normally exclusive to one job.

## Seed reruns of the two best grid configs (fresh seeds 0, 1, 2)

| config | AP mean ± sd | R@P90 mean ± sd | R@P95 mean ± sd |
| --- | --- | --- | --- |
| r=16, lr=2e-4 | 0.847 ± 0.008 | 0.477 ± 0.031 | 0.438 ± 0.055 |
| r=32, lr=2e-4 | 0.843 ± 0.029 | 0.488 ± 0.091 | 0.453 ± 0.081 |

The two are indistinguishable; r=16 is far more stable across seeds (AP sd 0.008 vs 0.029), so it
is the exploration base. Against ResNet-18 (AP 0.829, R@P90 0.465, one run), LoRA is ahead by
about 0.015 AP. That is within noise, so this is a tie, not a win.

## Batch 1 (queues/explore_1.txt): one knob at a time vs base (0.8B, r=16, lr=2e-4)

Single seed each; val. Sorted by AP. `best` = the step whose checkpoint was kept / steps run.

| change vs base | AP | log-loss | R@P90 | R@P95 | best |
| --- | --- | --- | --- | --- | --- |
| layers=[0,11] (lower half only) | 0.869 | 0.565 | 0.605 | 0.465 | 300/321 |
| alpha=16 (adapter scale 1 instead of 2) | 0.864 | 0.486 | 0.512 | 0.465 | 200/321 |
| vision-encoder LoRA (qkv, proj, fc1, fc2) | 0.856 | 0.517 | 0.453 | 0.407 | 321/321 |
| dropout=0.0 | 0.844 | 0.503 | 0.581 | 0.442 | 125/275 |
| MLP modules only | 0.842 | 0.557 | 0.465 | 0.453 | 225/321 |
| decision_loss_weight=3 | 0.829 | 0.783 | 0.465 | 0.372 | 50/200 |
| **base** | 0.824 | 0.615 | 0.442 | 0.360 | 321/321 |
| epochs=5 | 0.824 | 0.643 | 0.453 | 0.372 | 125/275 |
| lr=4e-4 | 0.824 | 0.649 | 0.395 | 0.384 | 100/250 |
| layers=[12,23] (upper half only) | 0.803 | 0.600 | 0.419 | 0.279 | 175/321 |
| attention/mixer modules only | 0.788 | 0.665 | 0.419 | 0.384 | 25/175 |
| r=64, alpha=128 | 0.785 | 0.650 | 0.407 | 0.326 | 225/321 |

Failed (not results): 1280 px, 2B, 4B and the projector rerun hit the home disk quota at
12:17 (run artifacts are now on scratch). They are requeued in batch 2.

**Read (tentative, single seed):** gentler, lower-capacity adaptation close to the image works
best. Lower layers beat upper layers by about twice the noise band. A smaller adapter scale
(alpha=16) gives the best log-loss. More capacity or a hotter schedule (r=64, lr=4e-4, more
epochs) does not help, and most runs peak before the end: overfitting pressure on 849 images.
MLP modules matter more than attention. decision_loss_weight=3 inflates log-loss
(overconfident) with no AP gain.

## Batch 2 (queues/explore_2.txt): requeued failures + combining the winners

Partial (13:37), single seed, final metrics from each run's selected checkpoint:

| change vs base | AP | log-loss | R@P90 |
| --- | --- | --- | --- |
| **model = Qwen3.5-4B** (LoRA, gradient checkpointing) | **0.901** | **0.417** | **0.640** |
| image_max_side = 1280 | 0.869 | 0.496 | 0.558 |
| model = Qwen3.5-2B | 0.862 | 0.507 | 0.535 |
| train_projector (after the dtype fix) | 0.849 | 0.482 | 0.535 |
| layers=[0,11] + alpha=16 | 0.842 | 0.559 | 0.384 |

The 4B is the first result clearly outside the noise band on log-loss (0.417 vs ~0.50 for the
next best), with AP +0.03 over the best 0.8B runs. Lower layers + alpha=16 did not stack (within
noise of base). Seed reruns are appended to this queue: 4B x2, layers=[0,11] x2, vision LoRA x2,
1280 px x1.

## Session summary (job 5922039, 2026-09-24): 38 exploration runs + 6 grid seed reruns

All numbers are val (184 frames, 22 games, 86 positives); the locked test set is untouched.
The comparison base is the 0.8B r=16, lr=2e-4 config: **AP 0.847 ± 0.008, R@P90 0.477** over
fresh seeds 0–2. Differences under ~0.03 AP are noise. `n` = number of seeds.

| config | n | AP | log-loss | R@P90 | R@P95 |
| --- | --- | --- | --- | --- | --- |
| **Qwen3.5-4B + vision-encoder LoRA** | 1 | **0.918** | **0.384** | **0.709** | **0.605** |
| **Qwen3.5-4B** | 4 | **0.892 ± 0.020** | 0.529 | 0.602 ± 0.058 | 0.517 |
| 0.8B, layers 0–11 + vision LoRA | 1 | 0.891 | 0.451 | 0.570 | 0.512 |
| 0.8B + vision-encoder LoRA | 3 | 0.869 ± 0.012 | 0.516 | 0.535 ± 0.071 | 0.450 |
| 0.8B at 1280 px | 2 | 0.862 ± 0.009 | 0.520 | 0.500 ± 0.082 | 0.436 |
| Qwen3.5-2B | 1 | 0.862 | 0.507 | 0.535 | 0.453 |
| 0.8B, layers 0–11 only | 3 | 0.852 ± 0.015 | 0.584 | 0.508 ± 0.084 | 0.403 |
| everything else (alpha, dropout, lr, epochs, rank, module subsets, projector, narrower layers) | 1 each | 0.77–0.86 | | | |

**Conclusions (preliminary, val only)**
1. **Model size is the clear lever.** 4B beats 0.8B by about +0.045 AP and +0.12 R@P90 across
   four seeds, outside the seed spread (fresh seeds only: 0.889). 2B (one run) sits in between.
2. **Vision-encoder LoRA helps modestly** (0.8B: +0.02 AP over 3 seeds, better log-loss). On 4B
   it gave the best single run of the session (0.918 / R@P90 0.709). A seed rerun was launched at
   16:36 to check it.
3. **Most other knobs are noise or harmful on 849 images.** Bigger rank, higher LR and more
   epochs hurt. Attention-only and upper-layers-only are the worst. "Lower layers only" looked
   like a win on seed 42 (0.869) but averages 0.852 over three seeds: winner's curse.
4. **Seed noise is large.** The same config spans ~0.06 AP and ~0.15 R@P90 across seeds. Single
   runs should not be trusted, and final choices need multi-seed means (or game-level CV).

**Suggested next steps:** 4B + vision LoRA with 3 seeds; try 9B (fits with gradient
checkpointing, ~1 h per run); latency (E-09), since 4B is ~5x the 0.8B's compute per frame and
the production budget is 5 s/frame; more labelled data as it arrives (the gains so far come from
model capacity rather than tuning).

**Operational notes:** home quota filled at 12:17 and failed 4 runs (artifacts moved to scratch;
all requeued). Another user's job shares this MIG slice (noisy timings). Fixed: generation dtype
crash with projector training; queue runner exit codes.

**Final run (17:05):** 4B + vision LoRA, seed 0: AP 0.894, R@P90 0.640, R@P95 0.581. Across its two
seeds (42, 0) it averages AP 0.906 and R@P90 0.675, slightly above plain 4B (0.892 / 0.602) but not
yet distinguishable. Needs a third seed.

## Job 5927060 (2026-09-24 17:50 to ~09:49): new families and LoRA styles

Hardware: RTX PRO 6000 **MIG 2g.48gb slice (47.4 GiB)**; nvidia-smi's 96 GB is the whole card.
Two queues share it (lane A: <=4B models; lane B: 8B/9B one at a time).

**Added:** `train.lora.style` = lora | dora | rslora | loha | lokr; model configs for
Qwen3-VL 2B/4B/8B, Qwen3.5-9B and InternVL3.5 2B/4B (HF-native). Gemma 3 skipped (gated, no token);
SmolVLM2 deferred (needs num2words).

**Smoke checks (E-07a, 64 frames, 50 steps; pipeline only):** rsLoRA, LoHa, LoKr, Qwen3-VL-4B,
InternVL3.5-4B + vision LoRA all pass incl. adapter reload (InternVL reload diff 0.008 vs ~1e-6
elsewhere; within tolerance). Qwen3-VL-8B and Qwen3.5-9B trained and predicted but failed the reload
check (two resident copies > 47 GiB); fixed in 1c68a64. The 9B memorised its 64 smoke frames (train
loss 0.10) with near-chance val AP 0.54; the full run will tell whether that matters.

**Fixed:** DoRA produced NaN on the first forward: Qwen3.5-0.8B layer 0 `in_proj_qkv` has 14 all-zero
weight rows and DoRA divides by row norms (0/0). DoRA now skips such targets (1553d17); Qwen3.5-4B has
none. 20-step recheck learns normally and reloads exactly.

**4B + vision LoRA, 4 seeds (42, 0, 1, 2):** AP 0.918, 0.894, 0.839, 0.910, **mean 0.890 ± 0.036**,
vs plain 4B 0.892 ± 0.020. No reliable gain from vision LoRA; the earlier "best" was seed luck.

**Are seed differences real? (split-half test, 21:10.)** 8 models (4B plain + 4B+vision, 4 seeds
each), val split into random game-halves 2,000 times. Seed rankings agree between halves (Spearman
mean +0.38, positive in 90% of splits), so bad seeds are genuinely worse. But the best model on one
half is the best on the other only 10% of the time (chance 12%): at 184 frames / 22 games the top
seed is not identifiable. Averaging all 8 seeds gives AP 0.910 without picking. Implication: compare
configs by multi-seed means; for a product, ensemble or drop clear duds rather than pick a "best seed".

**Evening results (single seed 42 unless noted; val):**

| config | AP | R@P90 | log-loss | best step |
| --- | --- | --- | --- | --- |
| Qwen3.5-4B + vision + class-balanced sampling | 0.919 | 0.733 | 0.413 | – |
| Qwen3.5-9B | 0.909 | 0.628 | 0.454 | 300 |
| Qwen3.5-4B + vision, 1280 px | 0.907 | 0.651 | 0.501 | 250 |
| Qwen3-VL-8B | 0.905 | 0.698 | 0.403 | 200 |
| *reference: Qwen3.5-4B plain, 4 seeds* | 0.892 ± 0.020 | 0.602 | 0.529 | |

All within ~0.03 AP of the 4B mean. Past 4B, size (8B/9B) shows no clear AP gain on one seed;
1280 px costs 2.5x compute for no clear gain. Balanced sampling and Qwen3-VL-8B lead on recall and
calibration; seed reruns are queued for both.

**Late-evening results (val):**
- Qwen3-VL-8B + vision LoRA: AP 0.901, R@P90 0.663, log-loss 0.644 (no gain; worse calibration).
- Qwen3.5-4B + vision, lr 1e-4: AP 0.895, R@P90 0.640, log-loss 0.520 (same as default lr).
- Qwen3-VL-4B (seed 42): AP 0.895, R@P90 0.628, log-loss 0.465 (level with Qwen3.5-4B).
- Qwen3-VL-8B, 2 seeds (42, 0): AP 0.905 / 0.890, mean 0.898; R@P90 mean 0.669; log-loss mean 0.44.
  vs Qwen3.5-4B (4 seeds) 0.892 / 0.602 / 0.529: modest recall/calibration edge, no AP edge, ~2x compute.

**Overnight (val):**
- Class-balanced 4B + vision, seed 0: AP 0.802, R@P90 0.430, **log-loss 1.831** (best step 25; val collapsed
  mid-run while train loss stayed ~0.7). With seed 42 at 0.919 / 0.733 / 0.413, balanced sampling looks
  unstable and prone to badly overconfident runs, not better. Seed 1 pending.
- InternVL3.5-4B (seed 42): AP 0.818, R@P90 0.465, log-loss 0.683: 0.07 AP below Qwen 4B (> 2x noise), a
  real negative. Its vision-LoRA and second-seed runs were swapped for Qwen3-VL-4B seed 1 and a 2-epoch
  Qwen3.5-4B run.
- Class-balanced sampling, final: 4B + vision seeds 42/0/1 = AP 0.919 / 0.802 / 0.849 (mean 0.857 ± 0.059);
  plain 4B + balanced AP 0.846, R@P90 0.570, log-loss 0.952 (best step 50, early-stopped). Three of four
  balanced runs peak by step 50 then degrade, with inflated log-loss. **Verdict: drop it** (unstable, not better).
- Qwen3-VL-2B: AP 0.860, R@P90 0.558, log-loss 0.510, same as Qwen3.5-2B (0.862 / 0.535). The Qwen families
  match at 2B and 4B.
- Qwen3-VL-8B, 3 seeds (42/0/1): AP 0.905 / 0.890 / 0.883, **mean 0.893**, R@P90 0.636, log-loss 0.464.
  Tied with Qwen3.5-4B (0.892 / 0.602 / 0.529); the early recall edge faded. Not worth ~2x compute.
- InternVL3.5-2B: AP 0.830, R@P90 0.442, log-loss 0.618 (below both Qwen 2B models, ~0.86).
  InternVL trails Qwen at both sizes.
- DoRA on Qwen3.5-4B (seed 42): AP 0.894, R@P90 0.535, log-loss 0.463, ~1.5x slower than LoRA. Same as plain.
- rsLoRA on Qwen3.5-4B: **diverged** (val AP 0.816 → 0.742 → 0.387 by step 75; decision CE rising), stopped at
  step 75. Cause: rsLoRA scales by alpha/sqrt(r) = 32/4 = 8 vs LoRA's alpha/r = 2, i.e. ~4x the effective
  step (lr 4e-4 already hurt). Not re-run: any rsLoRA setting equals plain LoRA with alpha' = alpha*sqrt(r),
  which the alpha sweeps already cover.
- Qwen3.5-9B seed 0: AP 0.891, R@P90 0.605, log-loss 0.583 (2-seed mean 0.900 / 0.616 / 0.518: tied with 4B).
- LoHa on Qwen3.5-4B: AP 0.823, R@P90 0.407, log-loss 0.580: 0.07 below plain LoRA (> 2x noise), a real
  negative (slower to learn, best at the last step; same r/alpha as LoRA, so possibly under-scaled).
- Qwen3.5-9B, 3 seeds (42/0/1): AP 0.909 / 0.891 / 0.905, **mean 0.902**, R@P90 0.624, log-loss 0.490.
  Most consistent across seeds; +0.01 AP over the 4B is within noise, at ~2x compute.
- Qwen3-VL-8B, 2 epochs (seed 42): AP 0.880, R@P90 0.581, log-loss 0.461 (best step 125/214). vs 3 epochs
  (3 seeds 0.883-0.905): slightly lower, within noise, one-third less training.
- LoKr on Qwen3.5-4B: AP 0.832, R@P90 0.465, log-loss 0.639 (best step 300/321). 0.06 below plain LoRA.
  **LoRA styles, verdict:** DoRA ties plain LoRA at ~1.5x time; rsLoRA diverged (scale 4x); LoHa and LoKr trail
  by 0.06-0.07 at LoRA's r/alpha. Plain LoRA stays the default.

## E-13 heat map probe (2026-09-25 09:00, prototype; `scripts/heatmap_probe.py`)

15 val frames (4 stitching, 3 lens flare, 2 glare, 2 clean-labelled false alarms, 2 fog, 2 clean) on the
Qwen3.5-4B seed-42 adapter. Output: outputs/client_report/heatmaps/heatmap_probe.html (NDA, not in git).
- **Occlusion, log-odds drop (6x4 grey tiles): promising.** Cold on clean frames (max 0-0.1); peaked on
  stitching and false-alarm frames (max 0.9-3.4); low and spread on fog (max 0.17-0.31). Probability drops
  saturate at P~0.999 (all ~0), hence log-odds.
- **Crop scoring (9 half-size crops): drop.** Out-of-distribution for a full-frame model; one clean frame's
  crop scored 0.97.
- The tarp "false alarm" (P 0.98) is hottest top-right, not on the tarp: the score is not driven by the tarp.
- No localisation labels exist, so maps cannot be scored yet. Next: rough boxes on ~50 issue frames
  (pointing-game metric), and ask the client what "problem area" should look like for crews.

**Final runs (val):**
- Qwen3-VL-4B, 3 seeds (42/0/1): AP 0.895 / 0.889 / 0.892, **mean 0.892**, R@P90 **0.667**, log-loss 0.465.
  Same AP as Qwen3.5-4B (0.892) with higher recall at 90% precision (0.667 vs 0.602) and better
  calibration (0.465 vs 0.529), at the same size. A modest but consistent edge: the recommended 4B candidate.
- Qwen3.5-4B, 2 epochs, 2 seeds: AP 0.886 / 0.875 (mean 0.881), R@P90 0.541, log-loss 0.446. Slightly below
  3 epochs on AP and recall (best checkpoint at the last step): keep 3 epochs.

## Job 5927060 summary (ended 09:01, 2026-09-25): ~40 runs across 7 families/sizes and 4 LoRA styles

Val, multi-seed means (n = seeds). Differences under ~0.03 AP are noise.

| config | n | AP | R@P90 | log-loss |
| --- | --- | --- | --- | --- |
| **Qwen3-VL-4B** | 3 | 0.892 ± 0.003 | **0.667** | **0.465** |
| Qwen3.5-9B | 3 | **0.902** ± 0.010 | 0.624 | 0.490 |
| Qwen3-VL-8B | 3 | 0.893 ± 0.011 | 0.636 | 0.464 |
| Qwen3.5-4B (baseline) | 4 | 0.892 ± 0.020 | 0.602 | 0.529 |
| Qwen3.5-4B + vision LoRA | 4 | 0.890 ± 0.036 | 0.637 | 0.482 |
| Qwen3.5-4B, 2 epochs | 3 | 0.879 ± 0.006 | 0.512 | 0.461 |
| 4B + vision + class-balanced | 3 | 0.857 ± 0.059 | 0.581 | 0.920 |
| single runs: DoRA 0.894; 1280 px 0.907; lr 1e-4 0.895; LoHa 0.823; LoKr 0.832; InternVL3.5 4B/2B 0.818/0.830; Qwen3-VL-2B 0.860; rsLoRA diverged | | | | |

**Conclusions.** (1) Everything at Qwen 4B+ plateaus at AP ~0.89-0.90: the ceiling is the data (849 training
frames), not the model or adapter. (2) **Recommended: Qwen3-VL-4B + plain LoRA, 3 epochs**: same AP as
Qwen3.5-4B, higher recall at 90% precision (+0.065), better calibration, lowest seed spread; 8B/9B add
≤ 0.01 AP at ~2x compute. (3) Dropped: InternVL, class balancing, LoHa/LoKr/rsLoRA, DoRA (no gain,
1.5x time), 2 epochs, 1280 px. (4) At the alert threshold, the Qwen3.5-4B catches all severity-4/5 val issues.
**Next:** more labelled data; latency on L4 (E-09) for Qwen3-VL-4B; seed ensemble vs latency budget;
localisation labels for heat maps (E-13).

## Job 5938799 (2026-09-25 09:14 to ~01:14): Qwen3-VL-4B batch x lr grid + exploration

Effective batch 4/8/16/32 (batch_size x grad_accum), lr 1e-4/2e-4/4e-4, eval every ~200 examples,
two seeds per cell (reference cell batch 8 / lr 2e-4 has 3 seeds: 0.892 / 0.667 / 0.465). Another user's job
shares the MIG slice (~13.6 GB), so queued runs use inference batch 16.

**lr 1e-4 row (seed 42), AP / R@P90 / log-loss:** batch 4 0.882 / 0.581 / 0.585; batch 8 0.874 / 0.547 / 0.476;
batch 16 0.868 / 0.465 / 0.489; batch 32 0.847 / 0.384 / 0.497. Larger batches do steadily worse at this lr
(fewer updates: 636 -> 81 steps over 3 epochs), i.e. undertrained.
- **Artifact:** batch 32 / lr 2e-4 (seed 42) reported AP 0.763 because it selected its **step-6** checkpoint (a lucky
  first-eval R@P90 spike, 0.419) and early-stopped at step 42/81; later checkpoints reached AP 0.84. Added
  `train.selection_start_fraction` (default 0 = unchanged): checkpoints before that fraction of training are
  never selected. The cell is requeued with 0.25. Large-batch cells are most exposed (fewest evals).
- **lr 2e-4 row (seed 42):** batch 4 0.879 / 0.628 / 0.502; batch 8 = reference 0.892 / 0.667 / 0.465 (3 seeds);
  batch 16 **0.893 / 0.640 / 0.443**; batch 32 artifact (rerun queued).
- **lr 4e-4 (seed 42):** batch 4 0.870 / 0.558 / 0.525; batch 8 0.817 / 0.442 / 0.927 (peaked step 50, too hot).
- Emerging: lr 2e-4 at batch 8-16 is the sweet spot; lr 1e-4 undertrains large batches, lr 4e-4 overshoots small ones.

**Seed-42 grid complete** (AP / R@P90 / log-loss; ref cell = 3 seeds):

| lr \ eff. batch | 4 | 8 | 16 | 32 |
| --- | --- | --- | --- | --- |
| 1e-4 | 0.882 / 0.581 / 0.585 | 0.874 / 0.547 / 0.476 | 0.868 / 0.465 / 0.489 | 0.847 / 0.384 / 0.497 |
| 2e-4 | 0.879 / 0.628 / 0.502 | **0.892 / 0.667 / 0.465** (ref) | **0.893 / 0.640 / 0.443** | artifact, rerun queued |
| 4e-4 | 0.870 / 0.558 / 0.525 | 0.817 / 0.442 / 0.927 | 0.857 / 0.547 / 0.494 | 0.885 / 0.547 / 0.472 |

Diagonal structure: the best lr rises with batch size (batch 32 does best at 4e-4, batch 4-8 at 1e-4-2e-4).
Best region: lr 2e-4 at batch 8-16. Seed 0 (queued) decides whether batch 16 beats batch 8.

**Exploration (seed 42, batch 8 / lr 2e-4 unless noted; ref 0.892 / 0.667 / 0.465):**
- LoRA r=8, alpha 16: AP 0.878, R@P90 0.535, log-loss 0.537 (best step 75/225).
- LoRA r=32, alpha 64: AP 0.855, R@P90 0.628, log-loss 0.528 (best step 100/250).
  Rank 16 stays; both picked mid-run checkpoints on recall while AP later reached ~0.885.
- LoRA alpha 16 (scale 1): AP 0.892, R@P90 0.593, log-loss 0.454: tie with alpha 32.
- Pre-filled labels at half weight: AP 0.878, R@P90 0.593, log-loss 0.470: no gain, so pre-fill labels look
  about as reliable as annotator labels for this task.
- Decision-loss weight λ=0 (plain token CE): AP 0.884, R@P90 **0.477**, log-loss 0.429; λ=2: AP 0.881, R@P90 0.570,
  log-loss 0.453; λ=1 (default, 3 seeds): 0.892 / **0.667** / 0.465. Without the extra term the yes/no token's CE
  stays ~0.5-0.6 for most of training (total loss ~0.05); AP catches up by the end but recall at 90% precision
  lags. Keep λ=1.
- LoRA dropout 0.1: AP 0.887, R@P90 0.593, log-loss 0.433 (tie).
- **LoRA on lower-half layers [0,17] of 36: AP 0.904, R@P90 0.651, log-loss 0.421**: best single Qwen3-VL-4B run on
  AP and calibration, with half the adapter parameters. Within noise (+0.012); the 0.8B lower-layers lead faded
  across seeds, so seeds 0 and 1 are queued.

**Recall by severity at 90% precision (multi-seed means; val n = 11/24/6/16/27 for severity 1-5):**
Qwen3.5-4B (4 seeds) 16/23/46/88/95%; Qwen3.5-9B (3) 15/46/56/83/83%; Qwen3-VL-4B (3) 21/42/61/96/89%.
**Correction:** the earlier "43/43 severity-4/5 caught" was a single seed (Qwen3.5-4B seed 42); across seeds it is 88%/95%.
- **Lower-half-layer LoRA [0,17], 3 seeds (42/0/1): AP 0.904 / 0.888 / 0.928, mean 0.907 ± 0.020, R@P90 0.674,
  log-loss 0.420** vs all-layer Qwen3-VL-4B 0.892 ± 0.003 / 0.667 / 0.465. +0.015 AP and better calibration with half
  the adapter parameters; within the ~0.03 band but held across seeds (unlike the 0.8B lower-layers lead).
  Seed 1 (0.928, R@P90 0.779) is the best single run of the project. Candidate new default; confirm on the test set.
- lr 1e-4 seed 0: batch 4 AP 0.887 / R@P90 0.628 (2-seed mean 0.885); batch 8 0.852 / 0.477 (mean 0.863).
- Batch 32 / lr 1e-4 seed 0: AP 0.792, best step 18/54 (early-stopped): same early-selection artifact as the
  batch-32 / lr 2e-4 cell. **Batch-32 cells are unreliable** under selection_start_fraction=0 (few evals, noisy
  recall). Only batch 32 / lr 2e-4 is rerun with 0.25 tonight; treat the batch-32 column as provisional.
- Seed 0: batch 4 / lr 2e-4 AP 0.897 / R@P90 0.640 (2-seed mean **0.888**); batch 16 / lr 2e-4 AP 0.873 / 0.477
  (2-seed mean **0.883**). The seed-42 batch-16 edge was seed luck: **batch 8 / lr 2e-4 stays the default**
  (0.892, 3 seeds); batch 4-16 at lr 2e-4 are all within noise.

## Classification in the loss (2026-09-25 21:55)

Added `train.class_loss_weight` (d109f46): extra CE on the crew-class name tokens of each issue (the class names
were already in the target but only got their share of the ~50-token average). Default 0 = unchanged.
**Baseline defect classification** (val crew-class micro / macro F1 from generated names, multi-seed means):
Qwen3-VL-4B all layers 0.450 / 0.291; Qwen3-VL-4B lower-half 0.432 / 0.305; Qwen3.5-4B 0.473 / 0.343.
Queued tonight (replacing lr-4e-4 seed-0 cells): lower-half with class weight 1 and 2; all layers with weight 2.
Success = higher class F1 without losing binary AP / R@P90.
- Seed 0: batch 4 / lr 4e-4 AP 0.894 / R@P90 0.651 (2-seed mean 0.882); batch 32 / lr 2e-4 AP 0.865 / 0.453 (best
  step 60/81, a genuine checkpoint rather than the early-selection artifact).
- **Class loss results (lower-half layers, seed 42)** vs lower-half baseline (3 seeds: class micro/macro F1
  0.432 / 0.305, class P 0.493; binary 0.907 / 0.674 / 0.420):
  - class_loss_weight 1: class micro 0.478, macro 0.394, P 0.590 R 0.401; binary AP 0.902, R@P90 0.686, LL 0.402.
  - class_loss_weight 2: class **micro 0.519, macro 0.414, P 0.714** R 0.408; binary AP 0.890, R@P90 0.651, LL 0.451.
  Class F1 up +0.05 to +0.11, mostly via precision, with binary metrics within noise. Class recall unchanged
  (~0.40): stitching (R 0.11-0.28), weather (0.11-0.22) and "other" (0.16) are rarely named. Single seeds; rerun.
- **All-layer Qwen3-VL-4B + class_loss_weight 2 (seed 42):** binary AP 0.908, R@P90 0.651, log-loss 0.415; class micro
  F1 **0.526** (P 0.588 R 0.476), macro 0.381, vs all-layer baseline (3 seeds) class 0.450 / 0.291 and binary
  0.892 / 0.667 / 0.465. The class-loss gain (+0.08 micro, +0.09 macro) repeats on a second config.
- **Batch 32 / lr 2e-4 rerun with selection_start_fraction 0.25:** AP 0.853, R@P90 0.477, best step 81/81 (vs the
  artifact's 0.763 at step 6): the fix works. Batch 32 genuinely prefers lr 4e-4 (0.885).

**Class loss, 2 seeds each (lower-half layers; baseline 3 seeds):**

| class_loss_weight | class micro F1 | class macro F1 | class P | binary AP | R@P90 | log-loss |
| --- | --- | --- | --- | --- | --- | --- |
| 0 (baseline) | 0.432 | 0.305 | 0.493 | **0.907** | **0.674** | **0.420** |
| 1 | 0.493 | **0.388** | 0.569 | 0.893 | 0.610 | 0.458 |
| 2 | **0.506** | 0.380 | **0.655** | 0.881 | 0.587 | 0.470 |

Class F1 gain is consistent (+0.06-0.07 micro, +0.08 macro, in all 5 class-loss runs across 2 configs), but seed 0
shows a **binary cost** (AP -0.014 to -0.026, R@P90 -0.06 to -0.09) that seed 42 didn't: a likely trade-off, not
free. Next: weight 0.5; select checkpoints on a combined binary+class metric; or keep binary selection and add a
separate class head (the MLP-head idea from the 2026-09-25 client sync).

## Job 5938799 summary (ended 00:22, 2026-09-26)

- **Batch x lr grid (Qwen3-VL-4B):** default batch 8 / lr 2e-4 stays (0.892). At lr 2e-4, batch 4/8/16 are within
  noise (0.888 / 0.892 / 0.883); best lr rises with batch size (batch 32 prefers 4e-4). Found and fixed an
  early-checkpoint selection artifact (`train.selection_start_fraction`).
- **Exploration:** lower-half-layer LoRA **0.907 ± 0.020 over 3 seeds** (best single run 0.928 / R@P90 0.779), a
  candidate default. No gain: rank 8/32, alpha 16, dropout 0.1, pre-fill down-weighting, decision weight 0/2.
- **Classification objective** (`train.class_loss_weight`, new): defect-class F1 +0.06-0.08, with a possible
  binary cost; see table above.

## Retrain on a fresh checkout (2026-11-15)

The September outputs were gone (fresh checkout; data, splits and outputs now live on scratch, symlinked).
Re-ran the audit: same split (849 / 184 / 186 frames; 106 / 22 / 24 games). Retrained the best recipe,
Qwen3-VL-4B + LoRA on lower-half layers [0,17], batch 8, lr 2e-4, 3 epochs, on an RTX PRO 6000 Blackwell
MIG 2g.48gb slice (the September runs used the same slice type; GPU nondeterminism still differs).

| seed | val AP | R@P90 | log-loss | ECE | class micro / macro F1 | best step |
| --- | --- | --- | --- | --- | --- | --- |
| **2** | **0.900** | **0.651** | **0.399** | **0.028** | 0.450 / 0.279 | 225 / 321 |
| 0 | 0.899 | 0.640 | 0.469 | 0.099 | 0.450 / 0.284 | 275 |
| 3 | 0.896 | 0.651 | 0.446 | 0.085 | 0.468 / 0.331 | 275 |
| 1 | 0.880 | 0.581 | 0.456 | 0.082 | 0.461 / 0.266 | 225 |

Mean AP 0.894 ± 0.008 (4 seeds) vs 0.907 ± 0.020 (3 seeds, September); seed 1 does not reproduce its
September 0.928, consistent with the ~±0.02 single-run spread. **Selected: seed 2** (AP tie, best R@P90 and
calibration), `outputs/E-07c/20261115T171807_212a7d93`.

**Locked test, seed 2 (run once; `outputs/E-07c/20261115T181549_add09f70`):** AP 0.887 [0.794, 0.952] (95% CI,
games resampled), ROC-AUC 0.851, ECE 0.085. At the val-fit P90 threshold (0.658): test P 0.965, R 0.585; at
P95 (0.818): P 1.000, R 0.479. At the 0.5 decision: P 0.802, R 0.691. Crew-class micro / macro F1 0.369 / 0.233
(stitching and miscalibration never named). Severity Spearman 0.729 (n=64). One parse failure out of 186.

**Inference (serving app `backend/`, `scripts/bench.py`, L40S capped at 24 GB as an L4 proxy; p95 per
frame):** score only 102 ms (bs 4); score + generation 3.64 s (bs 1), 1.10 s (bs 4), 656 ms (bs 8), 450 ms
(bs 16); occlusion heat map 2.57 s per flagged frame. Peak memory 8.4-11.4 GB. L4 estimates (scaled by
bandwidth / bf16 compute): ~0.3 s score only, ~1.3 s generation at bs 16, ~7.5 s per heat map. No L4 on ICE.
