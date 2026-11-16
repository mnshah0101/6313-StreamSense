"""Side-by-side comparison of evaluated runs (the Friday table). Reads metrics.json only."""

import json
from pathlib import Path
from typing import Any


def latest_completed(output_root: Path, experiment_id: str) -> list[Path]:
    """Most recent completed training run with val metrics, one per model in the experiment."""
    latest: dict[str, Path] = {}
    for run in sorted((output_root / experiment_id).glob("*/"), reverse=True):
        record = run / "run_record.json"
        if not record.exists() or not (run / "eval_val" / "metrics.json").exists():
            continue
        data = json.loads(record.read_text())
        if data.get("status") == "completed" and data.get("task") == "train":
            latest.setdefault(data["model"]["name"], run)
    return sorted(latest.values(), key=lambda r: r.name)


def _f(x: Any) -> str:
    return "–" if x is None else f"{x:.3f}"


def _ci(metrics: dict[str, Any], name: str) -> str:
    c = metrics["bootstrap_95ci_by_game"].get(name)
    if not c or c["point"] is None:
        return "–"
    return f"{c['point']:.3f} [{_f(c['lo'])}–{_f(c['hi'])}]"


def row(run: Path) -> dict[str, Any]:
    record = json.loads((run / "run_record.json").read_text())
    m = json.loads((run / "eval_val" / "metrics.json").read_text())
    ops = {op["fit"]["target_precision"]: op["fit"] for op in m.get("operating_points", [])}
    b = m["binary_at_model_decision"]
    user = m.get("user_subset", {})
    return {
        "experiment": record["experiment_id"],
        "model": record["model"]["name"],
        "run": run.name,
        "gpu": record["hardware"].get("observed_gpu") or "cpu",
        "ap": _ci(m, "average_precision") if m["has_scores"] else "–",
        "auc": _f(m.get("ranking", {}).get("roc_auc")),
        "acc": _f(b["accuracy"]),
        "p_r": f"{_f(b['precision'])} / {_f(b['recall'])}",
        "r_p90": _op(ops.get(0.9)),
        "r_p95": _op(ops.get(0.95)),
        "user_ap": _f(user.get("ranking", {}).get("average_precision")),
        "blur_ap": _f(
            m.get("terms", {}).get("per_label", {}).get("blur", {}).get("average_precision")
        ),  # fmt: skip
        "sev_rho": _f(m["severity"].get("spearman")),
        "parse_fail": _f(m["parse_failures"]["rate"]),
        "val_images": m["n_images"],
        "val_games": m["n_games"],
        "manifest": m["manifest_sha256"][:12],
        "lock": (m.get("locked_test_sha256") or "")[:12],
    }


def _op(op: dict[str, Any] | None) -> str:
    if op is None:
        return "–"
    return "unattainable" if not op["attainable"] else _f(op["recall"])


COLUMNS = [
    ("experiment", "Exp"), ("model", "Model"), ("ap", "AP [95% CI]"), ("auc", "ROC-AUC"),
    ("acc", "Acc@0.5"), ("p_r", "P / R @0.5"), ("r_p90", "R @ P≥0.90"),
    ("r_p95", "R @ P≥0.95"), ("user_ap", "User-subset AP"), ("blur_ap", "Blur AP"),
    ("sev_rho", "Severity ρ"), ("parse_fail", "Parse fail"),
]  # fmt: skip


def markdown(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "# StreamSense baselines\n\nNo completed runs found.\n"
    same = {r["manifest"] for r in rows} | {r["lock"] for r in rows}
    lines = [
        "# StreamSense baselines (validation split)", "",
        f"Val: {rows[0]['val_images']} images from {rows[0]['val_games']} games, split by game. "
        "Test split is locked and not evaluated here.", "",
        "| " + " | ".join(h for _, h in COLUMNS) + " |",
        "| " + " | ".join("---" for _ in COLUMNS) + " |",
    ]  # fmt: skip
    lines += ["| " + " | ".join(str(r[k]) for k, _ in COLUMNS) + " |" for r in rows]
    lines += [
        "",
        "- AP CIs: 95% percentile bootstrap over games. P≥ targets: max recall with val "
        "precision at or above the target; thresholds are fit on val, so these are optimistic.",
        "- Model checkpoints (CNN epochs) are also selected on val.",
        "- User-subset AP is on human-annotated rows, which are mostly negatives; its base rate "
        "differs from the full split.",
        f"- Same manifest and locked test for all rows: {'yes' if len(same) == 2 else 'NO'}.",
        "", "Runs: " + ", ".join(f"{r['experiment']}={r['run']} ({r['gpu']})" for r in rows),
    ]  # fmt: skip
    return "\n".join(lines) + "\n"


def completed_runs(output_root: Path, experiment_id: str) -> list[Path]:
    """Every completed training run of an experiment that has val metrics, oldest first."""
    runs = []
    for run in sorted((output_root / experiment_id).glob("*/")):
        record = run / "run_record.json"
        if record.exists() and (run / "eval_val" / "metrics.json").exists():
            data = json.loads(record.read_text())
            if data.get("status") == "completed" and data.get("task") == "train":
                runs.append(run)
    return runs


def grid_row(run: Path) -> dict[str, Any]:
    record = json.loads((run / "run_record.json").read_text())
    train = record["resolved_config"]["train"]
    m = json.loads((run / "eval_val" / "metrics.json").read_text())
    ops = {op["fit"]["target_precision"]: op["fit"] for op in m.get("operating_points", [])}
    return {
        "run": run.name,
        "model": record["model"]["name"],
        "r": train["lora"]["r"],
        "alpha": train["lora"]["alpha"],
        "lr": train["lr"],
        "seed": record["seed"],
        "dec_w": train.get("decision_loss_weight", "0 (pre)"),
        "subset": train.get("subset_size") or "all",
        "best_step": record["training"].get("best_step"),
        "steps": record["training"].get("steps"),
        "ap": m.get("ranking", {}).get("average_precision"),
        "log_loss": m.get("ranking", {}).get("log_loss"),
        "overrides": " ".join(
            o for o in record.get("overrides", []) if not o.startswith("+experiment")
        ),
        "r_p90": ops.get(0.9, {}).get("recall") if ops.get(0.9, {}).get("attainable") else None,
        "r_p95": ops.get(0.95, {}).get("recall") if ops.get(0.95, {}).get("attainable") else None,
        "parse_fail": m["parse_failures"]["rate"],
        "minutes": record.get("wall_time_s", 0) / 60,
    }


def grid_markdown(rows: list[dict[str, Any]]) -> str:
    cols = ["run", "overrides", "model", "r", "lr", "seed", "dec_w", "best_step", "steps",
            "ap", "log_loss", "r_p90", "r_p95", "parse_fail", "minutes"]  # fmt: skip
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for r in sorted(rows, key=lambda r: (-(r["r_p90"] or 0), -(r["ap"] or 0))):
        lines.append("| " + " | ".join(
            _f(r[c]) if isinstance(r[c], float) and c not in {"lr"} else str(r[c] or "–")
            for c in cols
        ) + " |")  # fmt: skip
    lines += ["", "Sorted by val recall at P>=0.90, then AP (the selection rule). Val-only; "
              "operating points are fit on val, so absolute values are optimistic."]  # fmt: skip
    return "\n".join(lines) + "\n"


def select_top_configs(
    rows: list[dict[str, Any]], k: int, keys: tuple[str, ...] = ("r", "lr")
) -> list[dict[str, Any]]:
    """Best k distinct configs by the selection rule (val R@P>=0.90, then AP)."""
    ranked = sorted(rows, key=lambda r: (-(r["r_p90"] or 0.0), -(r["ap"] or 0.0)))
    chosen: list[dict[str, Any]] = []
    for row in ranked:
        if all(any(row[x] != c[x] for x in keys) for c in chosen):
            chosen.append(row)
        if len(chosen) == k:
            break
    return chosen


def seed_summary(rows: list[dict[str, Any]], seeds: list[int]) -> str:
    """Mean ± sd over follow-up seeds per (r, lr). The grid run that selected the config is
    excluded from the mean (selection bias) and shown separately."""
    import statistics

    groups: dict[tuple, list[dict[str, Any]]] = {}
    for r in rows:
        if r["seed"] in seeds:
            groups.setdefault((r["model"], r["r"], r["lr"], r["dec_w"]), []).append(r)
    lines = ["| model | r | lr | seeds | AP mean ± sd | R@P≥0.90 mean ± sd | R@P≥0.95 mean ± sd |",
             "| --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip

    def ms(values: list[float | None]) -> str:
        v = [x if x is not None else 0.0 for x in values]
        sd = statistics.stdev(v) if len(v) > 1 else 0.0
        return f"{statistics.mean(v):.3f} ± {sd:.3f}"

    for (model, r, lr, _), g in sorted(groups.items(), key=lambda kv: kv[0][1:3]):
        lines.append(
            f"| {model} | {r} | {lr} | {sorted(x['seed'] for x in g)} | {ms([x['ap'] for x in g])}"
            f" | {ms([x['r_p90'] for x in g])} | {ms([x['r_p95'] for x in g])} |"
        )
    lines += ["", "Unattainable operating points count as recall 0. "
              "Val only; thresholds are fit on val."]  # fmt: skip
    return "\n".join(lines) + "\n"
