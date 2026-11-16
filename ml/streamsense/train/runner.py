"""Model-agnostic train -> predict -> evaluate. Models come only from the registry."""

from pathlib import Path
from typing import Any

import pandas as pd
from omegaconf import DictConfig, OmegaConf

from streamsense.data.ingest import training_rows
from streamsense.data.prepare import PreparedData, prepare
from streamsense.eval.predict import frames_from_manifest, write_predictions
from streamsense.eval.report import evaluate_run
from streamsense.models.registry import build_adapter
from streamsense.utils.hardware import (
    observed_hardware,
    release_accelerator_memory,
    resolve_device,
)
from streamsense.utils.run_record import RunContext


def record_data(run: RunContext, cfg: DictConfig, data: PreparedData) -> None:
    run.record.update({
        "manifest_sha256": data.ingestion.manifest_sha256,
        "labels_sha256": data.ingestion.labels_sha256,
        "archive_sha256": data.ingestion.archive_sha256,
        "locked_test_sha256": data.lock["test_keys_sha256"] if data.lock else None,
        "split_games": {k: len(v) for k, v in data.split.games.items()},
    })  # fmt: skip


def select_train(cfg: DictConfig, data: PreparedData, run: RunContext) -> pd.DataFrame:
    train, counts = training_rows(data.manifest[data.manifest["split"] == "train"], cfg.labels)
    if cfg.train.get("subset_size"):
        n = min(cfg.train.subset_size, len(train))
        train = train.sample(n=n, random_state=cfg.seed).reset_index(drop=True)
        counts["subset_size"] = n
    run.record["train_row_policy"] = counts | {"n_train": len(train)}
    return train


def run_training(cfg: DictConfig, run: RunContext) -> dict[str, Any]:
    data = prepare(cfg)
    record_data(run, cfg, data)
    root = data.ingestion.root
    train = frames_from_manifest(select_train(cfg, data, run), root)
    val = frames_from_manifest(data.manifest[data.manifest["split"] == "val"], root)
    test = frames_from_manifest(data.manifest[data.manifest["split"] == "test"], root)
    run.record["device"] = resolve_device(cfg)
    adapter = build_adapter(cfg)
    result = adapter.fit(train, val, run.output_dir)
    run.record["training"] = {"artifact": str(result.artifact_path), **result.details}
    # Test predictions are written for the final locked run; no test metrics are computed.
    for name, frames in (("val", val), ("test", test)):
        write_predictions(run.output_dir, name, adapter.predict(frames))
    adapter.save(run.output_dir / "adapter")  # after predict, so inference stats are included
    if cfg.train.get("verify_reload"):
        # Free the trained model first: two resident copies of an 8B/9B model exceed a
        # 48 GB slice shared with another run.
        del adapter
        release_accelerator_memory()
        run.record["reload_check"] = verify_reload(cfg, run.output_dir, val[:8])
    run.record["hardware"].update(observed_hardware())
    run.record["hardware"]["note"] = "Observed after training and prediction."
    eval_cfg = OmegaConf.merge(cfg, {"eval": {"split": "val", "final_test": False}})
    metrics = evaluate_run(eval_cfg, data, run.output_dir, run.output_dir / "eval_val")
    run.record["eval_val"] = str(run.output_dir / "eval_val")
    return metrics


def verify_reload(cfg: DictConfig, run_dir: Path, frames: list) -> dict[str, Any]:
    """Load the saved adapter into a fresh model and compare scores with saved predictions."""
    import numpy as np

    from streamsense.eval.predict import read_predictions

    fresh = build_adapter(cfg)
    fresh.load(run_dir / "adapter")
    saved = read_predictions(run_dir, "val")
    now = [p.scores.quality_issue for p in fresh.predict(frames)]
    before = [saved[f.key][1]["quality_issue"] for f in frames]
    diff = float(np.max(np.abs(np.array(now) - np.array(before))))
    result = {"frames": len(frames), "max_abs_score_diff": diff, "passed": diff < 1e-2}
    print(f"Reload check: {result}", flush=True)
    if not result["passed"]:
        raise RuntimeError(f"Reloaded adapter does not reproduce saved predictions: {result}")
    return result


def run_evaluation(cfg: DictConfig, run: RunContext) -> dict[str, Any]:
    if not cfg.eval.run_dir:
        raise ValueError("Set eval.run_dir=<training run directory with predictions/>")
    pred_dir = Path(cfg.eval.run_dir)
    if not pred_dir.is_absolute():
        pred_dir = Path(cfg.run.project_root) / pred_dir
    data = prepare(cfg)
    record_data(run, cfg, data)
    run.record["predictions_from"] = str(pred_dir)
    return evaluate_run(cfg, data, pred_dir, run.output_dir)
