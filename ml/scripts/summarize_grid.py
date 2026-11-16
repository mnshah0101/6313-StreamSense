"""Table of every completed run for the report experiments (e.g. the LoRA grid)."""

from pathlib import Path

import hydra
from omegaconf import DictConfig

from streamsense.config import CONFIG_DIR, register_configs
from streamsense.eval.compare import completed_runs, grid_markdown, grid_row, seed_summary

register_configs()


@hydra.main(version_base="1.3", config_path=str(CONFIG_DIR), config_name="config")
def main(cfg: DictConfig) -> None:
    root = Path(cfg.run.output_root)
    for experiment in cfg.report.experiments:
        runs = completed_runs(root, experiment)
        if runs:
            print(f"## {experiment}\n")
            rows = [grid_row(r) for r in runs]
            print(grid_markdown(rows))
            seeds = list(cfg.report.followup_seeds)
            if any(r["seed"] in seeds for r in rows):
                print(f"### Seed reruns ({seeds})\n")
                print(seed_summary(rows, seeds))


if __name__ == "__main__":
    main()
