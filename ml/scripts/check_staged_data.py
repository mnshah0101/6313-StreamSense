"""Hydra entry point for the local pre-commit data guard."""

from pathlib import Path

import hydra
from omegaconf import DictConfig, OmegaConf

from streamsense.config import CONFIG_DIR, register_configs
from streamsense.privacy import staged_violations

register_configs()


@hydra.main(version_base="1.3", config_path=str(CONFIG_DIR), config_name="config")
def main(cfg: DictConfig) -> None:
    """Fail if a staged artifact could publish private client data."""
    violations = staged_violations(
        Path(cfg.run.project_root).resolve(), OmegaConf.to_object(cfg.privacy), cfg.data.labels_file
    )
    for name, reason in violations:
        print(f"BLOCKED: {name}: {reason}")
    if violations:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
