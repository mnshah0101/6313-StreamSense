"""E-07b follow-up: override lines for the best grid configs x training seeds.

Only grid runs that match the current protocol are considered: full training set, the
current decision_loss_weight, and the split seed's training seed (the grid's fixed seed).
    python scripts/grid_followup.py +experiment=e07b_lora_grid
"""

from pathlib import Path

import hydra
from omegaconf import DictConfig

from streamsense.config import CONFIG_DIR, register_configs
from streamsense.eval.compare import completed_runs, grid_row, select_top_configs

register_configs()


@hydra.main(version_base="1.3", config_path=str(CONFIG_DIR), config_name="config")
def main(cfg: DictConfig) -> None:
    rows = [
        r for r in map(grid_row, completed_runs(Path(cfg.run.output_root), cfg.experiment_id))
        if r["subset"] == "all" and r["dec_w"] == cfg.train.decision_loss_weight
        and r["seed"] == cfg.seed
    ]  # fmt: skip
    for c in select_top_configs(rows, cfg.report.followup_top_k):
        for seed in cfg.report.followup_seeds:
            print(f"train.lora.r={c['r']} train.lr={c['lr']} seed={seed}")


if __name__ == "__main__":
    main()
