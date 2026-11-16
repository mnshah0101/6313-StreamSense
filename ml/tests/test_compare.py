import importlib.util
from pathlib import Path

from streamsense.eval.compare import select_top_configs


def row(r, lr, rp, ap):
    return {"r": r, "lr": lr, "r_p90": rp, "ap": ap}


def test_top_configs_follow_selection_rule_and_are_distinct():
    rows = [
        row(8, 1e-4, 0.40, 0.90),
        row(16, 2e-4, 0.50, 0.80),
        row(16, 2e-4, 0.45, 0.99),  # same config as the best: skipped
        row(32, 1e-4, 0.50, 0.85),  # ties on recall, wins on AP
        row(8, 2e-4, None, 0.95),  # unattainable recall ranks last
    ]
    top = select_top_configs(rows, 2)
    assert [(t["r"], t["lr"]) for t in top] == [(32, 1e-4), (16, 2e-4)]


def test_grid_overrides_cartesian_product():
    path = Path(__file__).parents[1] / "scripts" / "grid_overrides.py"
    spec = importlib.util.spec_from_file_location("grid_overrides", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lines = module.grid({"train.lr": "1e-4, 2e-4", "train.lora.r": "8,16"})
    assert lines == [
        "train.lora.r=8 train.lr=1e-4", "train.lora.r=8 train.lr=2e-4",
        "train.lora.r=16 train.lr=1e-4", "train.lora.r=16 train.lr=2e-4",
    ]  # fmt: skip
