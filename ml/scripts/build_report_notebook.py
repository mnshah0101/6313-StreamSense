"""Build the client report notebook in two forms from one set of cells.

1. `report.notebook` (committed, no outputs): computes everything from run artifacts.
2. `report.standalone_dir` (ignored): the same notebook with the aggregate data embedded as
   JSON and the rendering code inlined. It runs anywhere with pandas + matplotlib, and is
   written executed, with an HTML copy (code hidden) for sending to the client.

    python scripts/build_report_notebook.py
"""

import inspect
import json
import tempfile
from pathlib import Path

import hydra
import nbformat as nbf
from nbclient import NotebookClient
from nbconvert import HTMLExporter
from omegaconf import DictConfig

from streamsense.config import CONFIG_DIR, project_path, register_configs
from streamsense.eval import report_render
from streamsense.eval.client_report import collect
from streamsense.utils.io import write_text

register_configs()
md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell

INTRO = """# StreamSense: frame-quality model evaluation

**Team Parallax (Georgia Tech) for PlayOn Sports.** Every number and chart below is computed
from the project's saved predictions and metrics.

**What is being built.** A per-frame image-quality assessor for panoramic sports streams. Given
one sampled frame (production samples roughly one frame every 5 s per stream), it decides whether
the frame has a quality issue, names each defect, and grades severity 1–5.

**How to read the results.**
- **All results are on the validation split.** The test split is locked and has not been scored.
  It is reserved for one final run of the chosen models.
- **Precision comes first.** A false alarm can take a stream down, so the main metric is
  *recall at precision ≥ 0.90*: the share of real issues caught while at most 1 in 10 alerts is
  false. Average precision (AP) summarizes the whole precision–recall trade-off.
- **Uncertainty is shown.** Validation is small (see Section 2), so intervals are wide.
  Confidence intervals resample whole games, not individual frames."""

SETUP_REPO = """from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from hydra import compose, initialize_config_dir
from IPython.display import Markdown, display

from streamsense.config import CONFIG_DIR, PROJECT_ROOT, register_configs
from streamsense.eval import report_render as R
from streamsense.eval.client_report import collect

register_configs()
with initialize_config_dir(version_base="1.3", config_dir=str(CONFIG_DIR)):
    cfg = compose(config_name="config", overrides=["+experiment=e07b_lora_grid",
                                                   f"run.project_root={PROJECT_ROOT}"])
DATA = collect(Path(cfg.run.output_root), cfg.train.decision_loss_weight,
               list(cfg.report.followup_seeds), grid_seed=cfg.seed)"""

SETUP_TAIL = """pd.set_option("display.precision", 3)
plt.rcParams.update({"figure.dpi": 110, "font.size": 9})
display(Markdown(f"Data generated {DATA['generated_at']}. **Runs used:**\\n"
                 + "\\n".join(f"- {m['label']}: {m['note']}" for m in DATA["models"])))"""

CELLS = [
    ("md", INTRO),
    ("setup", None),
    (
        "md",
        """## 1. Results at a glance

One row per model, on the validation split. Single runs show a 95% game-bootstrap interval on AP.
The LoRA row averages several training seeds of one configuration (mean ± standard deviation).
- **Recall at P ≥ 0.90 / 0.95:** the best recall at which validation precision still meets the
  target. The threshold is fit on validation, so these values are optimistic until confirmed on
  the locked test set.
- **Accuracy at own decision:** each model's built-in yes/no answer, with no threshold tuning.
- **Human-labelled AP:** the same metric on frames labelled by an annotator rather than
  pre-filled. These rows are mostly negatives, so the base rate differs from the full split.""",
    ),
    ("code", "R.headline(DATA)"),
    (
        "code",
        """fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
R.plot_pr(DATA, axes[0])
R.plot_recall_at_precision(DATA, axes[1])
fig.tight_layout()""",
    ),
    (
        "md",
        """Left: each curve is one model's precision–recall trade-off on validation (for LoRA groups, the
run closest to the group's mean AP). The dashed line is the 0.90 precision target, and a curve that stays above it further to
the right is better. Right: recall at the precision ≥ 0.90 threshold. Lines are game-bootstrap
95% intervals for single runs; separate dots are separate training seeds.""",
    ),
    (
        "md",
        """## 2. Data

Dataset V1 is a zip of frames, one folder per game, plus one labels JSON. Each label has a
`decision` (`valid` = has an issue, `not` = no issue, `duplicate` = removed by the client), a
free-text comma-separated `term` list, an image-level `severity` (1–5), and a `source`
(`prefill` or `user`). Label rules applied:
- **Duplicates:** dropped. Their image files are absent, as expected.
- **`not`:** read as "no quality issue". This is inferred from the data and still needs
  client confirmation.
- **Missing severity:** positives without a severity stay in training and evaluation but are
  excluded from severity loss and metrics.
- **Terms:** lowercased, with aliases merged (e.g. `blurry` → `blur`), then mapped to the
  crew-facing classes. Unmapped terms go to `other`.""",
    ),
    (
        "code",
        """display(pd.DataFrame({"Label rows": DATA["audit"]["decision_counts"]}).T)
display(pd.DataFrame({"Dropped from usable set": DATA["audit"]["dropped"]}).T)
R.split_table(DATA)""",
    ),
    (
        "md",
        """**Split by game.** Frames from the same game (stream) are near-duplicates, so a random frame
split would leak. Whole games go to train, validation or test (70/15/15 by images). The
assignment is chosen, with a fixed seed, to balance the issue rate and per-class support
across splits. Games that share an identical image file would be kept together; none were
found. The test split is then **locked**: its games, image keys and a hash of their labels are
recorded, and every run verifies them. Thresholds, checkpoints and prompts are chosen on
validation only.""",
    ),
    (
        "code",
        """fig, ax = plt.subplots(figsize=(6.5, 3.2))
R.plot_support(DATA, ax)
fig.tight_layout()
R.class_support(DATA)""",
    ),
    (
        "md",
        """Class support is uneven. `weather` appears in too few games to be in all three splits, and
rare classes have too few validation examples for stable per-class numbers.

**Open label questions for PlayOn**
1. Does `decision = "not"` mean "no quality issue"?
2. Which crew class should `low contrast`, `high contrast`, `noise` and `distortion` map to?
   They currently go to `other`.
3. Can severity be given per defect? Today it is one value per image, so every issue in a
   frame inherits the image's severity.
4. How reliable are `prefill` labels compared with `user` labels? The table below shows how
   the label source differs between issue and no-issue frames.""",
    ),
    ("code", """pd.DataFrame(DATA["audit"]["source_by_decision"]).fillna(0).astype(int)"""),
    (
        "md",
        """## 3. Evaluation protocol

| Choice | Why |
| --- | --- |
| One shared metrics module for every model | All numbers are computed the same way from saved predictions. |
| Recall at precision ≥ 0.90 / 0.95 as the headline | False alarms are costly. The threshold is fit on validation and later applied unchanged to test. |
| AP and ROC-AUC | Threshold-free summaries of how well the score ranks frames. |
| 95% CIs by resampling games | Frames within a game are correlated; resampling frames would understate uncertainty. |
| Human-labelled subset reported separately | `prefill` and `user` labels may differ in quality. |
| Model-output parse failures count as "no issue" | A malformed answer cannot raise an alert. Failures are also reported separately. |
| Test split locked, scored once at the end | Keeps the final number independent of every tuning decision. |""",
    ),
    (
        "md",
        """## 4. Models and design choices

| Model | What it is | Key design choices |
| --- | --- | --- |
| BRISQUE/NIQE | Two classic no-reference quality scores + logistic regression | Full-resolution frames; fitted on train. Floor baseline, binary only. |
| ResNet-18 | ImageNet-pretrained CNN, 384 px short side, three heads: issue / defect terms / severity | Early stopping on val recall at P ≥ 0.90. The simple supervised bar a VLM must beat. |
| Qwen3.5-0.8B zero-shot | Small vision-language model prompted to return the JSON output contract | The answer is forced to start with `{"quality_issue":`. The issue score is P(true) vs P(false) for the next token, computed in full precision. The rest of the JSON is generated and then parsed. |
| Qwen2.5-VL-3B zero-shot | Larger VLM, same prompt | Same scoring. |
| Qwen3.5-0.8B / 4B + LoRA | Low-rank adapters on all language layers (r=16, lr=2e-4); vision encoder frozen | Answer-only loss, plus an extra loss on the true/false token (it is ~1 of ~50 answer tokens). Unknown severities are masked. The configuration comes from a 9-point grid, then 3 fresh seeds. |

**Why the VLM score is a token probability.** The model's self-reported "confidence" is not
calibrated. The probability of the `true` token is a real score, so it supports precision–recall
curves and threshold choice. Decisions, scores and checkpoint selection all use this one quantity.""",
    ),
    (
        "md",
        """### Per-class results (validation)

F1 at each model's own decision, plus AP where the model outputs per-class scores (ResNet-18
only). Classes with little validation support are unreliable. `–` means undefined (no
predictions of that class) or no validation support.""",
    ),
    ("code", "R.per_class(DATA)"),
    (
        "md",
        """### Severity (validation, true-issue frames with a known severity)

Rank correlation between predicted and labelled severity. The CNN has a severity head scored on
every true-issue frame. The VLMs state severity only on frames they flag, so their `n` can be
smaller. Severity is one value per image in the current labels.""",
    ),
    ("code", "R.severity(DATA)"),
    (
        "md",
        """## 5. LoRA fine-tuning details

**Grid.** Rank r ∈ {8, 16, 32} × learning rate ∈ {5e-5, 1e-4, 2e-4} at a fixed seed (42). The
best two configurations by validation recall at P ≥ 0.90 (ties broken by AP) are rerun with
seeds 0, 1 and 2. LoRA alpha is fixed at 32, so the effective adapter scale alpha/r changes with
rank. `dec_w` is the weight of the extra true/false-token loss. Rows with `0 (pre)` are earlier
runs without it, kept for comparison.""",
    ),
    ("code", "R.grid(DATA)"),
    (
        "md",
        """**Seed reruns.** Mean ± standard deviation over the fresh seeds. The seed-42 grid run that
selected each configuration is excluded, so the averages are not inflated by selection.""",
    ),
    ("code", "R.seed_summary(DATA)"),
    (
        "code",
        """fig, ax = plt.subplots(figsize=(6.5, 3.2))
R.plot_training_curve(DATA, ax)
fig.tight_layout()""",
    ),
    (
        "md",
        """**Engineering choices that affect results or trust**
- **True/false-token loss.** With a plain answer-token loss, the model learned the JSON format
  but barely learned the decision. Its scores on training frames hardly separated issues from
  clean frames. The extra loss term fixed this (compare the `dec_w` rows above).
- **Full-precision scoring.** Computing P(true) from 16-bit logits collapsed many frames onto
  identical scores. Scores are now computed in 32-bit from the final hidden state.
- **Fixed split seed.** Training-seed reruns share one train/validation split, so seed variation
  measures training randomness only.
- **Speed.** Fast linear-attention kernels, loss computed only on answer tokens (checked to equal
  the full computation), batch 8. Training is GPU-bound; one epoch takes about 1.5 minutes.""",
    ),
    (
        "md",
        """## 6. Reproducibility

Every run stores:
- its resolved configuration;
- a run record: git state, seed, dataset and label hashes, locked-test hash, model ID and
  immutable revision, package versions, observed GPU;
- predictions in the output contract, a score sidecar, and the metrics computed from them.

Dependencies are pinned in a lockfile.""",
    ),
    ("code", "R.reproducibility(DATA)"),
    (
        "md",
        """All runs share one manifest hash and one locked-test hash, so they used identical data and the
same held-out test set. The hardware is an RTX PRO 6000 Blackwell MIG slice, **not the target
L4**; latency measurements on L4-class hardware are a separate experiment (E-09).

## 7. Limitations and next steps
- **Validation only.** Results are provisional until the single locked-test run of the chosen
  models.
- **Small validation set.** Few validation games give wide intervals and noisy operating points.
  Differences of a few points between models are within noise.
- **Rare classes.** `weather`, `white_balance_saturation` and `miscalibration` have too little
  support for reliable per-class claims.
- **Label questions.** The open questions in Section 2 affect the targets directly.
- **Next steps.** Locked-test comparison of the chosen VLM, ResNet-18 and BRISQUE/NIQE; latency
  and streams-per-GPU (E-09); per-class threshold calibration (E-05); error slices by game and
  condition (E-06).""",
    ),
]


def build(setup_cells: list) -> nbf.NotebookNode:
    cells = []
    for kind, text in CELLS:
        if kind == "setup":
            cells += setup_cells
        else:
            cells.append(md(text) if kind == "md" else code(text))
    return nbf.v4.new_notebook(cells=cells, metadata={
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    })  # fmt: skip


@hydra.main(version_base="1.3", config_path=str(CONFIG_DIR), config_name="config")
def main(cfg: DictConfig) -> None:
    # 1. Repo notebook: no data, no outputs (safe to commit).
    repo = build([code(SETUP_REPO + "\n" + SETUP_TAIL)])
    nbf.write(repo, project_path(cfg, cfg.report.notebook))

    # 2. Standalone client notebook: aggregates embedded, renderer inlined, executed.
    data = collect(Path(cfg.run.output_root), cfg.train.decision_loss_weight,
                   list(cfg.report.followup_seeds), grid_seed=cfg.seed)  # fmt: skip
    render_src = inspect.getsource(report_render)
    standalone = build([
        md("*Self-contained copy: the data below are aggregates exported from the project's run "
           "artifacts. Requires only `pandas` and `matplotlib`.*"),
        code("# Plotting and table helpers (inlined from the project).\n" + render_src
             + "\n\nimport inspect as _inspect\nfrom types import SimpleNamespace\n\n"
             "R = SimpleNamespace(**{k: v for k, v in dict(globals()).items()\n"
             "                       if _inspect.isfunction(v) and not k.startswith('_')})"),
        code("import json\n\nimport matplotlib.pyplot as plt\nimport pandas as pd\nfrom IPython.display import Markdown, display\n\n"
             f"DATA = json.loads(r'''{json.dumps(data, indent=1)}''')\n" + SETUP_TAIL),
    ])  # fmt: skip
    out = project_path(cfg, cfg.report.standalone_dir)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:  # run outside the project: proves no imports
        NotebookClient(standalone, timeout=300, resources={"metadata": {"path": tmp}}).execute()
    nbf.write(standalone, out / "streamsense_report.ipynb")
    exporter = HTMLExporter(exclude_input=True)
    html, _ = exporter.from_notebook_node(standalone)
    write_text(out / "streamsense_report.html", html)
    print(f"repo notebook: {project_path(cfg, cfg.report.notebook)}")
    print(f"client notebook (executed): {out / 'streamsense_report.ipynb'}")
    print(f"client HTML (no code): {out / 'streamsense_report.html'}")


if __name__ == "__main__":
    main()
