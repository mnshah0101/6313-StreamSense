"""E-01: extract, validate, build the manifest, split by game, and lock the test set."""

import hydra
from omegaconf import DictConfig

from streamsense.config import CONFIG_DIR, register_configs
from streamsense.data.audit import run_audit
from streamsense.data.synthetic import synthetic_config
from streamsense.utils.run_record import recorded_run

register_configs()


@hydra.main(version_base="1.3", config_path=str(CONFIG_DIR), config_name="config")
def main(cfg: DictConfig) -> None:
    with recorded_run(cfg, "audit") as run:
        run_audit(synthetic_config(cfg, run.output_dir), run)


if __name__ == "__main__":
    main()
