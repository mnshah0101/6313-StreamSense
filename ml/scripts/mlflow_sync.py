"""Backfill: mirror every finished train/evaluate run under outputs/ into the local MLflow store.

Idempotent (runs already logged are skipped). Browse afterwards with:
    mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db --port 5000
"""

from pathlib import Path

import hydra
from omegaconf import DictConfig

from streamsense.config import CONFIG_DIR, register_configs
from streamsense.utils.tracking import log_run_dir

register_configs()


@hydra.main(version_base="1.3", config_path=str(CONFIG_DIR), config_name="config")
def main(cfg: DictConfig) -> None:
    artifacts = Path(cfg.logging.mlflow_artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)
    Path(cfg.logging.mlflow_uri.removeprefix("sqlite:///")).parent.mkdir(
        parents=True, exist_ok=True
    )
    logged = 0
    for record in sorted(Path(cfg.run.output_root).glob("*/*/run_record.json")):
        if log_run_dir(record.parent, cfg.logging.mlflow_uri, artifacts):
            logged += 1
    print(f"{logged} runs present in {cfg.logging.mlflow_uri}")


if __name__ == "__main__":
    main()
