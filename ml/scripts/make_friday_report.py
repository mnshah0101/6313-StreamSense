"""Compare evaluated runs in one table: latest completed run per report.experiments."""

from pathlib import Path

import hydra
from omegaconf import DictConfig

from streamsense.config import CONFIG_DIR, project_path, register_configs
from streamsense.eval.compare import latest_completed, markdown, row
from streamsense.utils.io import write_text

register_configs()


@hydra.main(version_base="1.3", config_path=str(CONFIG_DIR), config_name="config")
def main(cfg: DictConfig) -> None:
    if cfg.report.runs:
        runs = [project_path(cfg, r) for r in cfg.report.runs]
    else:
        root = Path(cfg.run.output_root)
        runs = [r for e in cfg.report.experiments for r in latest_completed(root, e)]
    text = markdown([row(r) for r in runs])
    write_text(project_path(cfg, cfg.report.output), text)
    print(text)


if __name__ == "__main__":
    main()
