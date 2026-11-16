"""Warm the selected model's disk cache for every usable image: model=<name>."""

import hydra
from omegaconf import DictConfig

from streamsense.config import CONFIG_DIR, register_configs
from streamsense.data.prepare import prepare
from streamsense.eval.predict import frames_from_manifest
from streamsense.models.registry import build_adapter
from streamsense.utils.run_record import recorded_run

register_configs()


@hydra.main(version_base="1.3", config_path=str(CONFIG_DIR), config_name="config")
def main(cfg: DictConfig) -> None:
    with recorded_run(cfg, "precompute") as run:
        data = prepare(cfg)
        frames = frames_from_manifest(data.manifest, data.ingestion.root)
        new = build_adapter(cfg).warm_cache(frames)
        run.record["cache"] = {"frames": len(frames), "computed": new}
        print(f"{cfg.model.name}: {new} computed, {len(frames) - new} already cached")


if __name__ == "__main__":
    main()
