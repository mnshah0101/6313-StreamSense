#!/usr/bin/env bash
# Any experiment: sbatch --gres=gpu:${GPU_TYPE}:1 slurm/train.sbatch +experiment=e02b_cnn
#SBATCH --job-name=streamsense-train
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x_%j.out
##SBATCH --account=TODO_ACCOUNT
##SBATCH --qos=TODO_QOS
source slurm/common.sh
python scripts/train.py "$@"
