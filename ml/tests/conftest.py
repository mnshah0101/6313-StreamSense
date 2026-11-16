"""Compose the real Hydra config for tests; data paths always point at synthetic fixtures."""

from collections.abc import Callable
from pathlib import Path

import pytest
from hydra import compose, initialize_config_dir
from omegaconf import DictConfig

from streamsense.config import CONFIG_DIR, register_configs
from streamsense.data.synthetic import write_synthetic_dataset

register_configs()


@pytest.fixture
def make_cfg(tmp_path: Path) -> Callable[..., DictConfig]:
    """Return a composer whose run outputs land in the test's temporary directory."""

    def compose_cfg(*overrides: str) -> DictConfig:
        with initialize_config_dir(version_base="1.3", config_dir=str(CONFIG_DIR)):
            return compose(
                config_name="config",
                overrides=[
                    f"run.project_root={tmp_path}",
                    f"run.output_root={tmp_path / 'outputs'}",
                    *overrides,
                ],
            )

    return compose_cfg


@pytest.fixture
def synthetic_root(tmp_path: Path) -> Path:
    return write_synthetic_dataset(tmp_path / "fixture", seed=0)
