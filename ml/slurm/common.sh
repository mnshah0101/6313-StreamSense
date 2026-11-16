#!/usr/bin/env bash
# Sourced by every sbatch script: environment, caches on fast local storage, diagnostics.
set -euo pipefail
cd "${STREAMSENSE_PROJECT_ROOT:-$SLURM_SUBMIT_DIR}"
# TODO(PACE): confirm module names with `module avail`; the project env ships its own Python
# and CUDA wheels (torch cu128), so no module is strictly required on ICE.
for m in ${STREAMSENSE_MODULES:-}; do module load "$m"; done
source .venv/bin/activate
# Home quota is small (30 GB): model and image caches go to node-local /tmp (rebuilt per job).
export HF_HOME="${HF_HOME:-/tmp/$USER/streamsense/hf}"
export TORCH_HOME="${TORCH_HOME:-/tmp/$USER/streamsense/torch}"
export STREAMSENSE_CACHE_DIR="${STREAMSENSE_CACHE_DIR:-/tmp/$USER/streamsense/cache}"
export TRITON_CACHE_DIR="${TRITON_CACHE_DIR:-/tmp/$USER/streamsense/triton}"  # kernel cache grows per shape
export HYDRA_FULL_ERROR=1
export PYTORCH_ALLOC_CONF=expandable_segments:True  # less fragmentation-driven OOM
mkdir -p logs "$HF_HOME" "$TORCH_HOME" "$STREAMSENSE_CACHE_DIR"
echo "host $(hostname) job ${SLURM_JOB_ID:-none} array ${SLURM_ARRAY_TASK_ID:-none}"
nvidia-smi -L || true
