# StreamSense

Per-frame image-quality experiments for Georgia Tech team Parallax and PlayOn Sports.
Precision takes priority: select the largest recall at a configured minimum precision.

## Quickstart

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then from this directory:

```bash
uv sync --locked --extra analysis --extra models --extra classical && source .venv/bin/activate
export HF_HOME=/tmp/streamsense/hf STREAMSENSE_CACHE_DIR=/tmp/streamsense/cache  # keep home quota free
pytest && ruff check .                                      # synthetic fixtures only, CPU
python scripts/train.py +experiment=e00_smoke               # end-to-end smoke on synthetic data
python scripts/audit.py +experiment=e01_audit               # manifest, game split, LOCKED test
python scripts/precompute.py model=cnn_resnet18             # optional: warm decode cache
python scripts/train.py +experiment=e02a_brisque_niqe       # each train run: fit, predict, val report
python scripts/train.py +experiment=e02b_cnn
python scripts/train.py +experiment=e03_zeroshot            # add model=qwen2_5_vl_3b for the 3B
python scripts/make_friday_report.py                        # side-by-side val table
```

Every training run writes `outputs/<experiment>/<run>/` with `run_record.json`, the adapter,
`predictions/{val,test}.jsonl` (output contract), `scores/` (score sidecar) and
`eval_val/metrics.{json,md}` plus plots and top-k error CSVs.

**Split and test lock.** The split is by game (one stream = one game): whole games go to
train/val/test (70/15/15 by images), balanced on positive rate and crew-class support, with
games that share an identical image kept together. The first audit writes
`splits/LOCKED_TEST.json` (test games, image keys, and a hash); every later run verifies it and
refuses to proceed if the test images or their labels changed. Thresholds, checkpoints and
prompts are chosen on val. Test metrics are only computed on request, once, for final models:

```bash
python scripts/evaluate.py eval.run_dir=outputs/E-02b/<run> eval.split=test eval.final_test=true
```

**Caches.** Decoded image canvases and BRISQUE/NIQE features are cached by image SHA-256
under `data.cache_dir` (`STREAMSENSE_CACHE_DIR`), so a changed image can never hit a stale entry.

## Experiment tracking (MLflow, local only)

Every finished train/evaluate run is mirrored to a local MLflow store (`mlruns/`, git-ignored),
with params (overrides, model/train config), headline val metrics, training curves, reports and
plots. No predictions or images are logged, and remote tracking URIs are rejected.
`python scripts/mlflow_sync.py` backfills older runs (idempotent). Browse from the project root:

```bash
mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db --host 127.0.0.1 --port 5000 \
  --allowed-hosts "*" --x-frame-options NONE  # needed behind VS Code's port-forward proxy
# The node is shared and the UI has no login: stop it when done (metrics are client-derived).
# laptop: forward the port (VS Code does this automatically), or
# ssh -L 5000:localhost:5000 -J <user>@login-ice.pace.gatech.edu <user>@<compute-node>
```

## Client report notebook

`notebooks/streamsense_report.ipynb` summarizes the data, split, evaluation protocol, design
choices and validation results. It reads only saved run artifacts. The committed file has no
outputs, and the commit guard rejects notebooks with outputs, because executed outputs contain
client-derived results. Render a shareable copy locally:

```bash
python -m nbconvert --to html --no-input --execute notebooks/streamsense_report.ipynb \
  --output-dir outputs/client_report --output streamsense_report
```

## Delivery checkpoints

1. Done: skeleton, typed configs, label inspection, commit guard.
2. Done: ingestion, SHA-256 duplicate audit, game split, locked test. Pixel-level corruption
   and perceptual-hash checks were skipped by decision (2026-09-23).
3. Done: BRISQUE/NIQE and ResNet-18 adapters, shared metrics, reports, CPU smoke test.
4. Done: VLM zero-shot inference and JSON parser (Qwen3.5-0.8B, Qwen2.5-VL-3B).
5. Done: LoRA training (decision-token loss, fp32 scoring), 9-point grid, seed reruns.
6. Latency and throughput benchmarks.
7. PACE setup, Slurm submission, and final operating docs.

See [implementation decisions](docs/DECISIONS.md).

## Experiments

| Config | Experiment | Status |
| --- | --- | --- |
| `e00_smoke` | E-00 environment and end-to-end smoke | runs |
| `e01_audit` | E-01 dataset audit and locked split | runs |
| `e02a_brisque_niqe` | E-02a classical binary baseline | runs |
| `e02b_cnn` | E-02b supervised ResNet-18 | runs |
| `e03_zeroshot` | E-03-lite small VLM zero-shot | runs |
| `e07a_lora_smoke` | E-07a adapter pipeline smoke | runs |
| `e07b_lora_grid` | E-07b rank/learning-rate sweep | runs (`scripts/grid_overrides.py`, `scripts/grid_followup.py`, `scripts/summarize_grid.py`) |
| `e05_calibrate` | E-05 validation threshold selection | operating points in every eval |
| `e06_slices` | E-06 error analysis | slices in every eval |
| `e09_latency` | E-09 latency and throughput | stage 6 |
| `e10_quant` | E-10 conditional quantization | TODO; outside implementation scope |

See [EXPERIMENTS.md](docs/EXPERIMENTS.md) for gates and ordering.

## Environments

The default locked install covers CPU inspection and tests without Torch or downloaded
model weights. `analysis` adds audit/evaluation libraries; `models` adds PyTorch,
Transformers, PEFT, and TensorBoard; `classical` adds pyiqa.
Later stages use `uv sync --locked --extra analysis --extra models --extra classical`.
These dependency sets are resolved in `uv.lock`; stage 1 exercises only the default set.

The `serve` extra is isolated because the pinned vLLM requires Transformers 4.x while
the HF model environment uses 5.x. Create a separate environment with
`UV_PROJECT_ENVIRONMENT=.venv-serve uv sync --locked --extra serve --extra analysis`.
Do not combine `serve` with `models` or `classical`. Backend compatibility and actual
model loading are validated at the VLM/benchmark checkpoints, not asserted by this scaffold.

Model revisions are immutable Hub commit SHAs in `conf/model/`. The baseline dependency
pins include Torch 2.10.0 / torchvision 0.25.0 and Transformers 5.3.0. The
[Qwen3.5 model documentation](https://huggingface.co/docs/transformers/v5.3.0/model_doc/qwen3_5)
is the compatibility reference; the stage 4 smoke test verifies the actual loader.

## NDA and local artifacts

Never commit client images, archives, labels, manifests, predictions, or checkpoints.
Keep data in `data/`; run artifacts go to ignored `outputs/` and `multirun/` directories.
The inspector writes `docs/DATA_SCHEMA.md` locally; this client-derived report is ignored.
The tracked [schema guide](docs/DATA_SCHEMA_TEMPLATE.md) contains no client label rows.
Fixtures are generated by Python code in temporary directories; there are no image or
label-JSON fixture exceptions to the commit guard.

The pre-commit hook checks staged paths **and staged content**, including renamed label
JSON and file signatures. It does not replace a review of material before publishing.
Logging is local CSV/TensorBoard; cloud logging and image uploads are disabled.
