"""Local MLflow tracking: mirror a finished run directory into a local store.

Reads only what the run already wrote (run_record.json, metrics, train_log.csv, plots), so the
training code is untouched and past runs can be backfilled. Idempotent: a run directory is
logged once (tag `run_dir`). Never logs predictions (they contain image keys) or images.
Browse with: mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

HEADLINE_ARTIFACTS = ["metrics.md", "metrics.json", "pr_curve.png", "reliability.png"]


def _flatten(prefix: str, value: Any, out: dict[str, str]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, out)
    else:
        out[prefix] = json.dumps(value) if isinstance(value, list) else str(value)


def params_from_record(record: dict[str, Any]) -> dict[str, str]:
    """Model/train/data settings that distinguish runs, plus the command-line overrides."""
    cfg = record.get("resolved_config", {})
    out: dict[str, str] = {}
    for section in ("model", "train"):
        _flatten(section, cfg.get(section, {}), out)
    for key in ("image_size", "canvas_aspect"):
        if key in cfg.get("data", {}):
            out[f"data.{key}"] = str(cfg["data"][key])
    out["seed"] = str(record.get("seed"))
    out["overrides"] = " ".join(record.get("overrides", [])) or "(none)"
    return {k: v[:6000] for k, v in out.items()}


def _op(m: dict[str, Any], target: float) -> float | None:
    for op in m.get("operating_points", []):
        if op["fit"]["target_precision"] == target and op["fit"]["attainable"]:
            return op["fit"]["recall"]
    return None


def metrics_from_eval(m: dict[str, Any]) -> dict[str, float]:
    """Headline val metrics (the same numbers the reports show)."""
    b = m.get("binary_at_model_decision", {})
    values = {
        "val_ap": m.get("ranking", {}).get("average_precision"),
        "val_roc_auc": m.get("ranking", {}).get("roc_auc"),
        "val_log_loss": m.get("ranking", {}).get("log_loss"),
        "val_ece": m.get("calibration", {}).get("ece"),
        "val_recall_at_p90": _op(m, 0.9),
        "val_recall_at_p95": _op(m, 0.95),
        "val_precision_at_decision": b.get("precision"),
        "val_recall_at_decision": b.get("recall"),
        "val_accuracy_at_decision": b.get("accuracy"),
        "val_user_subset_ap": m.get("user_subset", {}).get("ranking", {})
        .get("average_precision"),
        "val_parse_failure_rate": m.get("parse_failures", {}).get("rate"),
        "val_severity_spearman": m.get("severity", {}).get("spearman"),
    }  # fmt: skip
    return {k: float(v) for k, v in values.items() if v is not None}


def curve_from_log(path: Path) -> list[tuple[str, float, int]]:
    """(metric, value, step) for every numeric column of train_log.csv."""
    if not path.exists():
        return []
    rows = list(csv.DictReader(path.open()))
    out = []
    for i, row in enumerate(rows):
        step = int(float(row.get("step") or row.get("epoch") or i))
        for key, value in row.items():
            if key in {"step", "epoch"} or value in ("", None):
                continue
            try:
                out.append((f"curve_{key}", float(value), step))
            except ValueError:
                continue
    return out


def _ms(stamp: str | None) -> int | None:
    return int(datetime.fromisoformat(stamp).timestamp() * 1000) if stamp else None


def log_run_dir(run_dir: Path, tracking_uri: str, artifact_root: Path) -> str | None:
    """Log one run directory; returns the MLflow run id (existing or new), None if skipped."""
    record_path = run_dir / "run_record.json"
    if not record_path.exists():
        return None
    record = json.loads(record_path.read_text())
    if record.get("task") not in {"train", "evaluate"} or record.get("status") == "running":
        return None
    from mlflow.entities import Metric, Param
    from mlflow.tracking import MlflowClient

    client = MlflowClient(tracking_uri=tracking_uri)
    name = record["experiment_id"]
    exp = client.get_experiment_by_name(name)
    exp_id = exp.experiment_id if exp else client.create_experiment(
        name, artifact_location=(artifact_root / name).resolve().as_uri()
    )  # fmt: skip
    existing = client.search_runs(
        [exp_id], filter_string=f"tags.run_dir = '{run_dir.resolve()}'", max_results=1
    )
    if existing:
        return existing[0].info.run_id
    hw = record.get("hardware", {})
    tags = {
        "run_dir": str(run_dir.resolve()),
        "task": record["task"],
        "model": record.get("model", {}).get("name", ""),
        "git_commit": str(record.get("git", {}).get("commit")),
        "git_dirty": str(record.get("git", {}).get("dirty")),
        "manifest_sha256": str(record.get("manifest_sha256")),
        "locked_test_sha256": str(record.get("locked_test_sha256")),
        "observed_gpu": str(hw.get("observed_gpu")),
        "mlflow.note.content": record.get("error", {}).get("message", "")
        if record.get("status") == "failed" else "",
    }  # fmt: skip
    run = client.create_run(exp_id, start_time=_ms(record.get("started_at")),
                            tags=tags, run_name=run_dir.name)  # fmt: skip
    rid = run.info.run_id
    params = [Param(k, v) for k, v in params_from_record(record).items()]
    for i in range(0, len(params), 100):
        client.log_batch(rid, params=params[i : i + 100])
    eval_dir = run_dir / "eval_val" if (run_dir / "eval_val").exists() else run_dir
    now = _ms(record.get("finished_at")) or 0
    metrics = []
    if (eval_dir / "metrics.json").exists():
        values = metrics_from_eval(json.loads((eval_dir / "metrics.json").read_text()))
        metrics += [Metric(k, v, now, 0) for k, v in values.items()]
    if record.get("wall_time_s") is not None:
        metrics.append(Metric("wall_time_min", record["wall_time_s"] / 60, now, 0))
    metrics += [Metric(k, v, now, s) for k, v, s in curve_from_log(run_dir / "train_log.csv")]
    for i in range(0, len(metrics), 1000):
        client.log_batch(rid, metrics=metrics[i : i + 1000])
    for artifact in HEADLINE_ARTIFACTS:
        if (eval_dir / artifact).exists():
            client.log_artifact(rid, str(eval_dir / artifact))
    client.log_artifact(rid, str(record_path))
    status = "FINISHED" if record.get("status") == "completed" else "FAILED"
    client.set_terminated(rid, status=status, end_time=now or None)
    return rid
