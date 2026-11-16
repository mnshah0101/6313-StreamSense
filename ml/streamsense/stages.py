"""Explicit failures for interfaces whose implementation belongs to a later checkpoint."""

from collections.abc import Callable

import hydra
from omegaconf import DictConfig

from streamsense.config import CONFIG_DIR, register_configs
from streamsense.utils.run_record import recorded_run


def deferred_entrypoint(task: str, stage: int) -> Callable[..., None]:
    """Expose Hydra help/config composition without simulating a completed experiment."""
    register_configs()

    @hydra.main(version_base="1.3", config_path=str(CONFIG_DIR), config_name="config")
    def main(cfg: DictConfig) -> None:
        with recorded_run(cfg, task):
            raise NotImplementedError(
                f"{task} is scheduled for delivery stage {stage}. "
                "Stage 1 provides scripts/check_scaffold.py and scripts/inspect_labels.py. "
                "No training or evaluation has run."
            )

    return main
