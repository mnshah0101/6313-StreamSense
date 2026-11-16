#!/usr/bin/env bash
# API + embedded GPU worker with the real checkpoint, in one Slurm job (PACE dev/testing).
# Writes "host:port" to $STREAMSENSE_API_DATA_DIR/endpoint so the UI dev server can proxy to it.
#
#   cd backend && sbatch -A coc -q coc-ice -p coc-gpu,ice-gpu,ice-bw-gpu --gres=gpu:1 \
#     --constraint="gpu-l40s|A100-80GB|gpu-h100|gpu-h200|gpu-a40|gpu-rtxpro-blackwell" \
#     --export=ALL,API_VENV=$HOME/scratch/streamsense/api-venv-gpu scripts/serve_gpu.sbatch
#
# Settings come from .env (media backend, S3 bucket, AWS keys, data dir); the model defaults
# below can be overridden there. One process owns the SQLite DB (never share it over NFS
# between a login-node API and a compute-node worker).
#SBATCH --job-name=ss-api-gpu
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH --output=%x_%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-.}"
set -a
[ -f .env ] && source .env
set +a
export HF_HOME=/tmp/$USER/streamsense/hf HF_HUB_DISABLE_XET=1 PYTORCH_ALLOC_CONF=expandable_segments:True
export STREAMSENSE_CACHE_DIR=/tmp/$USER/streamsense/cache TMPDIR=/tmp/$USER/streamsense/tmp
mkdir -p "$TMPDIR"
export STREAMSENSE_API_BACKEND=${STREAMSENSE_API_BACKEND:-streamsense}
export STREAMSENSE_API_RUN_DIR=${STREAMSENSE_API_RUN_DIR:-$HOME/scratch/streamsense/outputs/E-07c/20261115T171807_212a7d93}
export STREAMSENSE_API_STREAMSENSE_REPO=${STREAMSENSE_API_STREAMSENSE_REPO:-$(cd .. && pwd)/ml}
export STREAMSENSE_API_DATA_DIR=${STREAMSENSE_API_DATA_DIR:-$HOME/scratch/streamsense/api-data}
export STREAMSENSE_API_EMBEDDED_WORKER=true STREAMSENSE_API_BATCH_SIZE=${STREAMSENSE_API_BATCH_SIZE:-16}
PORT=${PORT:-$("${API_VENV:?set API_VENV}/bin/python" -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1])")}
mkdir -p "$STREAMSENSE_API_DATA_DIR"
echo "$(hostname -f):$PORT" > "$STREAMSENSE_API_DATA_DIR/endpoint"
nvidia-smi -L || true
echo "API on http://$(hostname -f):$PORT (endpoint file: $STREAMSENSE_API_DATA_DIR/endpoint)"
exec "$API_VENV/bin/uvicorn" app.main:app --host 0.0.0.0 --port "$PORT"
