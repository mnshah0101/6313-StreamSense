"""Train any registered model, predict val/test, and evaluate on val."""

import hydra
from omegaconf import DictConfig

from streamsense.config import CONFIG_DIR, register_configs
from streamsense.data.synthetic import synthetic_config
from streamsense.train.runner import run_training
from streamsense.utils.run_record import recorded_run

register_configs()


@hydra.main(version_base="1.3", config_path=str(CONFIG_DIR), config_name="config")
def main(cfg: DictConfig) -> None:
    with recorded_run(cfg, "train") as run:
        cfg = synthetic_config(cfg, run.output_dir)
        run_training(cfg, run)
        print(f"Run: {run.output_dir}\nVal report: {run.output_dir / 'eval_val' / 'metrics.md'}")


if __name__ == "__main__":
    main()
