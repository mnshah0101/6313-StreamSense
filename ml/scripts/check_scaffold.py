"""CPU-only scaffold check. The model-training E-00 smoke arrives in stage 3."""

import hydra
from omegaconf import DictConfig, OmegaConf

from streamsense.config import CONFIG_DIR, register_configs
from streamsense.data.inspection import inspect_dataset
from streamsense.data.synthetic import write_synthetic_dataset
from streamsense.utils.run_record import recorded_run

register_configs()


@hydra.main(version_base="1.3", config_path=str(CONFIG_DIR), config_name="config")
def main(cfg: DictConfig) -> None:
    """Generate fixtures under the run directory and exercise the real label inspector."""
    with recorded_run(cfg, "check_scaffold") as run:
        root = write_synthetic_dataset(run.output_dir / "synthetic_fixture", cfg.seed)
        inspection_cfg = OmegaConf.merge(
            cfg,
            {
                "data": {
                    "input_mode": "extracted",
                    "zip_path": None,
                    "extract_dir": str(root),
                    "root_subdir": "",
                    "labels_file": "labels.json",
                    "schema_report": str(run.output_dir / "DATA_SCHEMA.md"),
                }
            },
        )
        run.record["fixture_data_config"] = OmegaConf.to_container(
            inspection_cfg.data, resolve=True
        )
        inspect_dataset(inspection_cfg, run)
        run.record["scope"] = "synthetic label inspection; no model training or evaluation"
        print("Scaffold check passed. End-to-end model smoke is pending stage 3.")


if __name__ == "__main__":
    main()
