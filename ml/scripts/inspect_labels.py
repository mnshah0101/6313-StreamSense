"""Inspect Dataset V1 labels without extracting or modifying client data."""

import hydra
from omegaconf import DictConfig

from streamsense.config import CONFIG_DIR, register_configs
from streamsense.data.inspection import inspect_dataset
from streamsense.utils.run_record import recorded_run

register_configs()


@hydra.main(version_base="1.3", config_path=str(CONFIG_DIR), config_name="config")
def main(cfg: DictConfig) -> None:
    """Write aggregate schema counts and fail on label-changing discrepancies."""
    with recorded_run(cfg, "inspect_labels") as run:
        inspect_dataset(cfg, run)


if __name__ == "__main__":
    main()
