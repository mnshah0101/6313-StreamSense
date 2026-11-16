"""Print one override string per grid point from an experiment's hydra.sweeper.params.

Used by the Slurm array (index i runs line i) and by local loops; each grid point runs in its
own process. Example: python scripts/grid_overrides.py +experiment=e07b_lora_grid
"""

import itertools
import sys

from hydra import compose, initialize_config_dir

from streamsense.config import CONFIG_DIR, register_configs


def grid(params: dict[str, str]) -> list[str]:
    keys = sorted(params)
    values = [[v.strip() for v in str(params[k]).split(",")] for k in keys]
    return [" ".join(f"{k}={v}" for k, v in zip(keys, combo, strict=True))
            for combo in itertools.product(*values)]  # fmt: skip


def main() -> None:
    register_configs()
    with initialize_config_dir(version_base="1.3", config_dir=str(CONFIG_DIR)):
        cfg = compose(config_name="config", overrides=sys.argv[1:], return_hydra_config=True)
    for line in grid(dict(cfg.hydra.sweeper.params or {})):
        print(line)


if __name__ == "__main__":
    main()
