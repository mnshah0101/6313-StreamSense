"""Collect the client report's data from run artifacts into one plain, JSON-safe dict.

Only aggregates leave this module: no images, image keys, game IDs or label descriptions.
Rendering lives in `report_render.py` (pandas/matplotlib only) so the standalone notebook
can embed this dict and run anywhere.
"""

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from streamsense.eval.compare import completed_runs, grid_row, select_top_configs

BASELINES = [
    ("BRISQUE/NIQE", "E-02a", "brisque_niqe"),
    ("ResNet-18", "E-02b", "cnn_resnet18"),
    ("Qwen3.5-0.8B zero-shot", "E-03-lite", "qwen3_5_0_8b"),
    ("Qwen2.5-VL-3B zero-shot", "E-03-lite", "qwen2_5_vl_3b"),
]
LORA = "Qwen3.5-0.8B + LoRA"
LORA_4B = "Qwen3.5-4B + LoRA"


@dataclass
class ModelRuns:
    label: str
    runs: list[Path]
    note: str


def _record(run: Path) -> dict[str, Any]:
    return json.loads((run / "run_record.json").read_text())


def _metrics(run: Path) -> dict[str, Any]:
    return json.loads((run / "eval_val" / "metrics.json").read_text())


def latest_audit(root: Path) -> dict[str, Any]:
    runs = sorted((root / "E-01").glob("*/audit_summary.json"))
    if not runs:
        raise FileNotFoundError("Run scripts/audit.py +experiment=e01_audit first")
    return json.loads(runs[-1].read_text())


def select_models(
    root: Path, decision_loss_weight: float, seeds: list[int], grid_seed: int
) -> list[ModelRuns]:
    """Baselines: latest completed run. LoRA: best grid config on val (selection rule), then its
    fresh-seed reruns; falls back to the selecting grid run (marked) if reruns are missing."""
    out = []
    for label, exp, model in BASELINES:
        runs = [r for r in completed_runs(root, exp) if _record(r)["model"]["name"] == model]
        if runs:
            out.append(ModelRuns(label, [runs[-1]], f"latest completed {exp} run"))
    rows = [(r, grid_row(r)) for r in completed_runs(root, "E-07b")]
    grid = [row for _, row in rows if row["subset"] == "all" and row["seed"] == grid_seed
            and row["dec_w"] == decision_loss_weight]  # fmt: skip
    if grid:
        best = select_top_configs(grid, 1)[0]
        same = [r for r, row in rows if (row["r"], row["lr"], row["dec_w"], row["subset"])
                == (best["r"], best["lr"], best["dec_w"], "all")]  # fmt: skip
        fresh = [r for r in same if _record(r)["seed"] in seeds]
        cfg = f"r={best['r']}, lr={best['lr']:g}"
        if fresh:
            note = f"best grid config ({cfg}); {len(fresh)} fresh seeds, mean ± sd"
            out.append(ModelRuns(LORA, fresh, note))
        else:
            note = f"best grid config ({cfg}); the selecting run (optimistic; reruns pending)"
            out.append(ModelRuns(LORA, [r for r in same if _record(r)["seed"] == grid_seed], note))

    def plain_4b(run: Path) -> bool:
        rec = _record(run)
        lora = rec["resolved_config"]["train"]["lora"]
        return rec["model"]["name"] == "qwen3_5_4b" and not lora.get("vision_target_modules")

    big = [r for r in completed_runs(root, "E-07c") if plain_4b(r)]
    if big:
        seeds_used = sorted(_record(r)["seed"] for r in big)
        out.append(ModelRuns(LORA_4B, big, f"exploration E-07c, r=16, lr=2e-4; {len(big)} seeds "
                             f"{seeds_used}, mean ± sd"))  # fmt: skip
    return out


def _op(m: dict[str, Any], target: float) -> float | None:
    for op in m.get("operating_points", []):
        if op["fit"]["target_precision"] == target:
            return op["fit"]["recall"] if op["fit"]["attainable"] else 0.0
    return None


def _ci(m: dict[str, Any], name: str) -> list[float] | None:
    c = m.get("bootstrap_95ci_by_game", {}).get(name)
    return [c["lo"], c["hi"]] if c and c["lo"] is not None else None


def run_summary(run: Path) -> dict[str, Any]:
    """Aggregate metrics of one run (val split)."""
    m, r = _metrics(run), _record(run)
    crew = {}
    by_class = m.get("slices", {}).get("by_crew_class", {})
    for c, v in m.get("crew_classes", {}).get("per_label", {}).items():
        crew[c] = {"support": by_class.get(c, {}).get("n", v.get("support", 0)),
                   "f1": v.get("f1"), "ap": v.get("average_precision")}  # fmt: skip
    sev = m.get("severity", {})
    curve = None
    log = run / "train_log.csv"
    if log.exists() and "val_ap" in log.read_text().splitlines()[0]:
        rows = list(csv.DictReader(log.open()))
        curve = {
            "step": [int(x["step"]) for x in rows],
            "val_ap": [float(x["val_ap"]) for x in rows],
        }
    pr = m.get("pr_curve")
    return {
        "run": run.name,
        "seed": r["seed"],
        "manifest": r["manifest_sha256"][:12],
        "lock": (r.get("locked_test_sha256") or "")[:12],
        "gpu": r["hardware"].get("observed_gpu") or "CPU",
        "curve": curve,
        "metrics": {
            "ap": m.get("ranking", {}).get("average_precision"),
            "ap_ci": _ci(m, "average_precision"),
            "roc_auc": m.get("ranking", {}).get("roc_auc"),
            "r_p90": _op(m, 0.9),
            "r_p95": _op(m, 0.95),
            "op_recall_ci": _ci(m, "op_recall"),
            "accuracy": m["binary_at_model_decision"]["accuracy"],
            "user_ap": m.get("user_subset", {}).get("ranking", {}).get("average_precision"),
            "parse_fail": m["parse_failures"]["rate"],
            "pr_curve": {"precision": pr["precision"], "recall": pr["recall"]} if pr else None,
            "crew": crew,
            "severity": {"n": sev["n"], "Spearman": sev["spearman"], "Kendall": sev["kendall"],
                         "MAE (1–5 scale)": sev["mae"]} if "spearman" in sev else None,
        },
    }  # fmt: skip


def collect(root: Path, decision_loss_weight: float, seeds: list[int], grid_seed: int
            ) -> dict[str, Any]:  # fmt: skip
    audit = latest_audit(root)
    splits = {
        name: {"Games": c["games"], "Images": c["images"], "Issue rate": c["positive_rate"],
               "Human-labelled": c["source"].get("user", 0),
               "Positives missing severity": c["severity_missing_positives"]}
        for name, c in audit["split_counts"].items()
    }  # fmt: skip
    models = select_models(root, decision_loss_weight, seeds, grid_seed)
    keys = ("r", "alpha", "lr", "seed", "subset", "best_step", "steps", "ap", "r_p90", "r_p95")
    grid = []
    for run in completed_runs(root, "E-07b"):
        row = grid_row(run)
        extra = {"dec_w": str(row["dec_w"]), "minutes": round(row["minutes"], 1)}
        grid.append({k: row[k] for k in keys} | extra)
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "audit": {
            "decision_counts": audit["inspection"]["counts"]["decision"],
            "dropped": audit["dropped"],
            "source_by_decision": audit["inspection"]["source_by_decision"],
            "splits": splits,
            "class_support": {s: c["crew_classes"] for s, c in audit["split_counts"].items()},
        },
        "models": [
            {"label": m.label, "note": m.note, "runs": [run_summary(r) for r in m.runs]}
            for m in models
        ],  # fmt: skip
        "grid": grid,
        "followup_seeds": seeds,
    }
