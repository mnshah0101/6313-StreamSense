# PACE / ICE

**Environment.** `uv sync --locked --extra analysis --extra models --extra classical` (the
project bundles Python 3.11 and CUDA 12.8 torch wheels; no CUDA module is needed). Export
`HF_HOME=/tmp/streamsense/hf STREAMSENSE_CACHE_DIR=/tmp/streamsense/cache` in interactive jobs:
home is 30 GB. Caches in `/tmp` are node-local and rebuild on first use (a few minutes).

**Data.** Keep `data/streamsense_partition.zip` in the project's ignored `data/` directory (or
set `data.zip_path`). `scripts/audit.py` extracts it once (checksum marker) and verifies the
locked test set on every run.

**Runs.** Interactive: `python scripts/train.py +experiment=<id>`. Batch: see `slurm/README.md`.
Check jobs with `squeue -u $USER` and `sacct -j <id> --format=JobID,State,Elapsed,MaxRSS`.

**Observed hardware (2026-09-23/24).** RTX PRO 6000 Blackwell as a MIG 2g.48gb slice, not an
L4. Every run record stores the observed GPU. Latency reports (E-09) must say so in their first line.

**Home quota.** Keep `HF_HOME`, `STREAMSENSE_CACHE_DIR` and `TRITON_CACHE_DIR` on `/tmp`, and run artifacts (`outputs/`, `mlruns/`) on scratch (symlinked). Home filled up on 2026-09-24 and failed four runs.

**Limits hit.** Home quota (99% full): caches were moved to `/tmp`. Job RAM 16 GB: LoRA
preprocessing was changed to per-batch.
