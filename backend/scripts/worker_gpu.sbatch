#!/usr/bin/env bash
# Extra GPU worker only (no API, no web app): claims jobs from the shared Postgres queue.
# Add as many as you like to process videos in parallel.
#
#   cd backend && sbatch -A coc -q coc-ice -p coc-gpu,ice-gpu,ice-bw-gpu --gres=gpu:1 \
#     --constraint="gpu-h200|gpu-h100|gpu-rtxpro-blackwell|A100-80GB|gpu-l40s" \
#     --export=ALL,API_VENV=$HOME/scratch/streamsense/api-venv-gpu scripts/worker_gpu.sbatch
#
# Needs STREAMSENSE_API_DB_URL (Postgres) and the S3 settings in .env.
#SBATCH --job-name=ss-worker
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH --output=%x_%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-.}"
set -a
[ -f .env ] && source .env
set +a
case "${STREAMSENSE_API_DB_URL:-}" in postgres*) ;; *) echo "worker_gpu needs a Postgres STREAMSENSE_API_DB_URL"; exit 1;; esac
export HF_HOME=/tmp/$USER/streamsense/hf HF_HUB_DISABLE_XET=1 PYTORCH_ALLOC_CONF=expandable_segments:True
export STREAMSENSE_CACHE_DIR=/tmp/$USER/streamsense/cache TMPDIR=/tmp/$USER/streamsense/tmp
mkdir -p "$TMPDIR"
export STREAMSENSE_API_BACKEND=${STREAMSENSE_API_BACKEND:-streamsense}
export STREAMSENSE_API_RUN_DIR=${STREAMSENSE_API_RUN_DIR:-$HOME/scratch/streamsense/outputs/E-07c/20261115T171807_212a7d93}
export STREAMSENSE_API_STREAMSENSE_REPO=${STREAMSENSE_API_STREAMSENSE_REPO:-$(cd .. && pwd)/ml}
export STREAMSENSE_API_DATA_DIR=/tmp/$USER/streamsense/worker-data STREAMSENSE_API_BATCH_SIZE=${STREAMSENSE_API_BATCH_SIZE:-0}  # 0 = sized to the GPU
mkdir -p "$STREAMSENSE_API_DATA_DIR"
# Rolling mode (scripts/pace_workers.sh): queue this job's successor now, so a GPU worker is
# always running or waiting in line. A job killed at its time limit loses only its lease; the
# successor resumes that video from its last saved batch. Stop with `pace_workers.sh stop`.
if [ -n "${SS_ROLL_ARGS:-}" ] && [ ! -e "$HOME/.streamsense/stop-pace-workers" ]; then
  # shellcheck disable=SC2086
  sbatch $SS_ROLL_ARGS --dependency=afterany:$SLURM_JOB_ID "$SLURM_SUBMIT_DIR/scripts/worker_gpu.sbatch" \
    || echo "could not queue the successor job"
fi
nvidia-smi -L || true
exec "${API_VENV:?set API_VENV}/bin/python" -m app.worker
