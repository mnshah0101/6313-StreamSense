#!/usr/bin/env bash
# One LoRA run per array index; line i of the override list is job i (0-based).
# Submit (GPU type is an argument, never hard-coded):
#   python scripts/grid_overrides.py +experiment=e07b_lora_grid > logs/grid.txt       # 9 lines
#   python scripts/grid_followup.py  +experiment=e07b_lora_grid > logs/grid.txt       # or seeds
#   sbatch --array=0-$(( $(wc -l < logs/grid.txt) - 1 )) --gres=gpu:${GPU_TYPE}:1 \
#          --export=ALL,GRID_FILE=logs/grid.txt slurm/lora_grid_array.sbatch
#SBATCH --job-name=streamsense-lora
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x_%A_%a.out
##SBATCH --account=TODO_ACCOUNT
##SBATCH --qos=TODO_QOS
source slurm/common.sh
overrides=$(sed -n "$(( SLURM_ARRAY_TASK_ID + 1 ))p" "${GRID_FILE:?set GRID_FILE}")
[ -n "$overrides" ] || { echo "no override line for index $SLURM_ARRAY_TASK_ID"; exit 1; }
echo "overrides: $overrides"
# shellcheck disable=SC2086
python scripts/train.py +experiment=${EXPERIMENT:-e07b_lora_grid} $overrides
