#!/usr/bin/env bash
# sbatch scripts/gpu_smoke.sbatch RUN_DIR PLAYONSPORTS_REPO   (from backend/)
#SBATCH --job-name=ss-api-smoke
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=00:45:00
#SBATCH --output=%x_%j.out
set -euo pipefail
export HF_HOME=/tmp/$USER/streamsense/hf HF_HUB_DISABLE_XET=1 PYTORCH_ALLOC_CONF=expandable_segments:True
export STREAMSENSE_CACHE_DIR=/tmp/$USER/streamsense/cache
cd "${SLURM_SUBMIT_DIR:-.}"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
nvidia-smi -L || true
"${API_VENV:?set API_VENV}/bin/python" scripts/gpu_smoke.py "$1" "$2" "${3:-8}"
