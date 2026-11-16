"""Evaluate saved predictions from a training run: eval.run_dir=<run dir>.

Test evaluation needs eval.split=test eval.final_test=true and the locked test file.
"""

import hydra
from omegaconf import DictConfig

from streamsense.config import CONFIG_DIR, register_configs
from streamsense.train.runner import run_evaluation
from streamsense.utils.run_record import recorded_run

register_configs()


@hydra.main(version_base="1.3", config_path=str(CONFIG_DIR), config_name="config")
def main(cfg: DictConfig) -> None:
    with recorded_run(cfg, "evaluate") as run:
        run_evaluation(cfg, run)
        print((run.output_dir / "metrics.md").read_text())


if __name__ == "__main__":
    main()
