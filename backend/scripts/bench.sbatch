#!/usr/bin/env bash
# sbatch --gres=gpu:l40s:1 scripts/bench.sbatch RUN_DIR PLAYONSPORTS_REPO OUT_JSON [extra bench args]
#SBATCH --job-name=ss-bench
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=%x_%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-.}"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
export HF_HOME=/tmp/$USER/streamsense/hf HF_HUB_DISABLE_XET=1 PYTORCH_ALLOC_CONF=expandable_segments:True
export STREAMSENSE_CACHE_DIR=/tmp/$USER/streamsense/cache
nvidia-smi -L || true
run_dir=$1 repo=$2 out=$3; shift 3
"${API_VENV:?set API_VENV}/bin/python" scripts/bench.py run "$run_dir" "$repo" --out "$out" "$@"
