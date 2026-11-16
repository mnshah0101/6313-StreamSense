"""Evaluate saved predictions: metrics.json, metrics.md, plots, and error CSVs."""

from pathlib import Path
from typing import Any

import matplotlib
import pandas as pd
from omegaconf import DictConfig

from streamsense.data import taxonomy as tx
from streamsense.data.prepare import PreparedData
from streamsense.data.split import SplitLockError
from streamsense.eval import metrics as mt
from streamsense.eval.predict import build_table, read_predictions
from streamsense.utils.io import write_json, write_text

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def eval_params(cfg: DictConfig) -> mt.EvalParams:
    grid = tuple(cfg.eval.threshold_grid) if cfg.eval.threshold_candidates == "grid" else None
    return mt.EvalParams(
        precision_targets=tuple(cfg.eval.precision_targets),
        selection_target=cfg.eval.selection_precision_target,
        bootstrap_samples=cfg.eval.bootstrap_samples,
        confidence_bins=cfg.eval.confidence_bins,
        seed=cfg.seed,
        grid=grid,
    )


def vocabulary(data: PreparedData, tax: tx.Taxonomy) -> tuple[str, ...]:
    """Level-1 vocabulary fitted on train only, identical for every model."""
    return tx.fit_vocabulary(data.manifest.loc[data.manifest["split"] == "train", "terms"], tax)


def evaluate_run(
    cfg: DictConfig, data: PreparedData, pred_dir: Path, out_dir: Path
) -> dict[str, Any]:
    """Score one training run's saved predictions on cfg.eval.split."""
    split = cfg.eval.split
    if split == "test":
        if not cfg.eval.final_test:
            raise SplitLockError("Test evaluation requires eval.final_test=true")
        if data.lock is None:
            raise SplitLockError("Refusing test evaluation without splits/LOCKED_TEST.json")
    tax = tx.Taxonomy.from_config(cfg.taxonomy)
    vocab = vocabulary(data, tax)
    tables = {}
    for name in {"val", split}:
        rows = data.manifest[data.manifest["split"] == name]
        tables[name] = build_table(rows, read_predictions(pred_dir, name), tax, vocab)
    result = mt.evaluate_table(
        tables[split],
        tables["val"],
        eval_params(cfg),
        term_labels=vocab,
        crew_labels=list(tax.crew_classes),
        fit_is_eval=split == "val",
    )
    result = {
        "split": split,
        "predictions_from": str(pred_dir),
        "locked_test_sha256": data.lock["test_keys_sha256"] if data.lock else None,
        "manifest_sha256": data.ingestion.manifest_sha256,
        "term_vocabulary": list(vocab),
    } | result
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "metrics.json", _jsonable(result))
    write_text(out_dir / "metrics.md", markdown(result, cfg))
    write_errors(tables[split], out_dir / "errors", cfg.eval.top_k_errors)
    plots(result, out_dir)
    return result


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, float) and value != value:
        return None
    return value


def write_errors(table: pd.DataFrame, out: Path, k: int) -> None:
    """Top-k false positives/negatives by score. Paths only; images are never copied."""
    cols = ["key", "image_path", "game_id", "source", "score", "true_terms", "pred_terms",
            "true_severity", "pred_severity", "description", "explanation"]  # fmt: skip
    fp = table[~table["y"] & table["pred"]]
    fn = table[table["y"] & ~table["pred"]]
    if table["score"].notna().all():
        fp, fn = fp.sort_values("score", ascending=False), fn.sort_values("score")
    out.mkdir(parents=True, exist_ok=True)
    fp.head(k)[cols].to_csv(out / "false_positives.csv", index=False)
    fn.head(k)[cols].to_csv(out / "false_negatives.csv", index=False)


def plots(result: dict[str, Any], out: Path) -> None:
    if "pr_curve" in result:
        fig, ax = plt.subplots(figsize=(4.5, 4))
        pr = result["pr_curve"]
        ax.plot(pr["recall"], pr["precision"])
        for op in result["operating_points"]:
            ax.axhline(op["fit"]["target_precision"], ls=":", lw=1, color="gray")
        ax.set(xlabel="Recall", ylabel="Precision", title=f"PR ({result['split']})",
               xlim=(0, 1), ylim=(0, 1.02))  # fmt: skip
        fig.tight_layout()
        fig.savefig(out / "pr_curve.png", dpi=120)
        plt.close(fig)
    if "calibration" in result:
        fig, ax = plt.subplots(figsize=(4.5, 4))
        bins = result["calibration"]["bins"]
        ax.plot([0, 1], [0, 1], ls=":", color="gray")
        ax.plot([b["confidence"] for b in bins], [b["observed"] for b in bins], marker="o")
        ax.set(xlabel="Predicted P(issue)", ylabel="Observed issue rate",
               title=f"Reliability (ECE {result['calibration']['ece']:.3f})")  # fmt: skip
        fig.tight_layout()
        fig.savefig(out / "reliability.png", dpi=120)
        plt.close(fig)


def _f(x: Any) -> str:
    return "–" if x is None else f"{x:.3f}" if isinstance(x, float) else str(x)


def _ci(ci: dict[str, Any], name: str) -> str:
    c = ci.get(name)
    if not c or c["point"] is None:
        return "–"
    return f"{c['point']:.3f} [{_f(c['lo'])}, {_f(c['hi'])}]"


def markdown(r: dict[str, Any], cfg: DictConfig) -> str:
    b, ci = r["binary_at_model_decision"], r["bootstrap_95ci_by_game"]
    lines = [
        f"# {cfg.experiment_id} · {cfg.model.name} · split={r['split']}", "",
        f"{r['n_images']} images, {r['n_games']} games. "
        f"Parse failures: {r['parse_failures']['count']}. 95% CIs resample games.", "",
        "## Binary (quality issue)", "",
        "| Metric | Value [95% CI] |", "| --- | --- |",
        f"| Precision @ model decision | {_ci(ci, 'precision')} |",
        f"| Recall @ model decision | {_ci(ci, 'recall')} |",
        f"| F1 @ model decision | {_ci(ci, 'f1')} |",
        f"| Accuracy | {_f(b['accuracy'])} |",
    ]  # fmt: skip
    if r["has_scores"]:
        lines += [
            f"| Average precision | {_ci(ci, 'average_precision')} |",
            f"| ROC-AUC | {_f(r['ranking']['roc_auc'])} |",
            f"| ECE | {_f(r['calibration']['ece'])} |",
            "", f"### Precision-first operating points (thresholds fit on "
            f"{r['operating_points_fit_on']})", "",
            "| Target P | Threshold | Val P | Val R | Eval P | Eval R |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]  # fmt: skip
        for op in r["operating_points"]:
            f, e = op["fit"], op["eval"]
            if not f["attainable"]:
                lines.append(f"| {f['target_precision']} | unattainable on val | | | | |")
                continue
            lines.append(
                f"| {f['target_precision']} | {f['threshold']:.4f} | {_f(f['precision'])} | "
                f"{_f(f['recall'])} | {_f(e['precision'])} | {_f(e['recall'])} |"
            )
    c = b["confusion"]
    lines += ["", f"Confusion at model decision: TP {c['tp']}, FP {c['fp']}, FN {c['fn']}, "
              f"TN {c['tn']}.", ""]  # fmt: skip
    for level in ("crew_classes", "terms"):
        if level not in r:
            continue
        lines += [f"## Per defect: {level}", "", "| Label | Support | P | R | F1 | AP |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]  # fmt: skip
        for label, m in r[level]["per_label"].items():
            if m.get("metrics") == "omitted":
                lines.append(f"| {label} | 0 | – | – | – | – |")
                continue
            lines.append(
                f"| {label} | {m['support']} | {_f(m['precision'])} | {_f(m['recall'])} | "
                f"{_f(m['f1'])} | {_f(m.get('average_precision'))} |"
            )
        mi = r[level]["micro"]
        lines += [f"\nMicro P/R/F1 {_f(mi['precision'])}/{_f(mi['recall'])}/{_f(mi['f1'])}, "
                  f"macro F1 {_f(r[level]['macro_f1'])}.", ""]  # fmt: skip
    s = r["severity"]
    if "spearman" in s:
        lines += ["## Severity (true-issue rows with known severity)", "",
                  f"n={s['n']} (excluded {s['excluded']}), Spearman {_f(s['spearman'])}, "
                  f"Kendall {_f(s['kendall'])}, MAE {_f(s['mae'])}, "
                  f"exact after rounding {_f(s['exact_rounded'])}.", ""]  # fmt: skip
    if "user_subset" in r:
        u = r["user_subset"]
        ub = u["binary_at_model_decision"]
        lines += ["## User-labelled subset", "",
                  f"{u['n_images']} images. P {_f(ub['precision'])}, R {_f(ub['recall'])}"
                  + (f", AP {_f(u['ranking']['average_precision'])}" if u["has_scores"] else "")
                  + ".", ""]  # fmt: skip
    return "\n".join(lines)
