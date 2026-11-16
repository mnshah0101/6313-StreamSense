# Slurm scripts

- `common.sh`: sourced by every job. Activates `.venv`, puts HF/Torch/image caches on node-local
  `/tmp/$USER/streamsense` (home quota is 30 GB), and prints the GPU.
- `train.sbatch`: any experiment, e.g. `sbatch --gres=gpu:$GPU_TYPE:1 slurm/train.sbatch +experiment=e02b_cnn`.
- `lora_grid_array.sbatch`: one LoRA run per array index, with line *i* of `GRID_FILE` as its
  overrides. Generate the file with `scripts/grid_overrides.py` (the 9-point grid) or
  `scripts/grid_followup.py` (best 2 configs x seeds 0,1,2).

The GPU type is always passed on the command line (`--gres=gpu:<type>:1`); literal `#SBATCH`
lines cannot expand variables. On ICE the resource name seen so far is
`rtx_pro_6000_blackwell` (a MIG 2g.48gb slice). Account and QOS are commented placeholders.
Measured LoRA peak usage (Qwen3.5-0.8B, batch 8): ~23 GB GPU and ~10.5 GB host RAM, so
`--mem=32G` leaves headroom. A 16 GB job was OOM-killed before per-batch preprocessing was added.
