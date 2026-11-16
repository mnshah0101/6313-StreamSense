"""The only place metrics are computed. Inputs are plain tables; outputs are plain JSON.

Every model is evaluated through `evaluate_table` with the same inputs:
one row per image with truth columns and the model's normalized prediction columns.

Required columns: key, game_id, source, y, pred, parse_failed, true_terms, pred_terms,
true_crew, pred_crew, true_severity, pred_severity, weather_related.
Optional score columns (NaN/None when a model has no score): score, severity_score,
term_scores (dict), crew_scores (dict).
"""

import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import kendalltau, spearmanr
from sklearn.metrics import average_precision_score, roc_auc_score

from streamsense.eval.thresholds import OperatingPoint, apply_threshold, recall_at_precision


@dataclass(frozen=True)
class EvalParams:
    precision_targets: tuple[float, ...]
    selection_target: float
    bootstrap_samples: int
    confidence_bins: int
    seed: int
    grid: tuple[float, ...] | None = None  # None = exact search over unique scores


def _div(a: float, b: float) -> float | None:
    return a / b if b else None


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None or p + r == 0:
        return None if p is None or r is None else 0.0
    return 2 * p * r / (p + r)


def has_scores(values: pd.Series) -> bool:
    return len(values) > 0 and bool(values.notna().all())


def binary_metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    y, pred = np.asarray(y, bool), np.asarray(pred, bool)
    tp, fp = int((y & pred).sum()), int((~y & pred).sum())
    fn, tn = int((y & ~pred).sum()), int((~y & ~pred).sum())
    p, r = _div(tp, tp + fp), _div(tp, tp + fn)
    return {
        "n": int(len(y)), "positives": int(y.sum()),
        "precision": p, "recall": r, "f1": _f1(p, r),
        "accuracy": _div(tp + tn, len(y)),
        "false_positive_rate": _div(fp, fp + tn),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }  # fmt: skip


def ranking_metrics(y: np.ndarray, score: np.ndarray) -> dict[str, float | None]:
    """Threshold-free quality of a score; undefined when only one class is present."""
    y = np.asarray(y, bool)
    if y.all() or not y.any():
        return {"average_precision": None, "roc_auc": None, "log_loss": None}
    p = np.clip(np.asarray(score, float), 1e-7, 1 - 1e-7)
    log_loss = -np.mean(np.where(y, np.log(p), np.log(1 - p)))
    return {
        "average_precision": float(average_precision_score(y, score)),
        "roc_auc": float(roc_auc_score(y, score)),
        "log_loss": float(log_loss),  # smooth; comparable only for probability-like scores
    }


def selection_key(y: np.ndarray, score: np.ndarray, target: float) -> tuple[float, float]:
    """Checkpoint selection: val recall at precision >= target, ties broken by AP."""
    op = recall_at_precision(y, score, target)
    ap = ranking_metrics(y, score)["average_precision"]
    return (op.recall or 0.0, ap or 0.0)


def pr_curve(y: np.ndarray, score: np.ndarray) -> dict[str, list[float]]:
    from sklearn.metrics import precision_recall_curve

    p, r, t = precision_recall_curve(np.asarray(y, bool), score)
    return {"precision": p.tolist(), "recall": r.tolist(), "thresholds": t.tolist()}


def calibration(y: np.ndarray, score: np.ndarray, bins: int) -> dict[str, Any]:
    """Equal-width reliability bins and expected calibration error of P(issue)."""
    y, s = np.asarray(y, float), np.clip(np.asarray(score, float), 0, 1)
    idx = np.minimum((s * bins).astype(int), bins - 1)
    table, ece = [], 0.0
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        conf, acc = float(s[m].mean()), float(y[m].mean())
        ece += m.mean() * abs(conf - acc)
        table.append({"bin": b, "n": int(m.sum()), "confidence": conf, "observed": acc})
    return {"ece": float(ece), "bins": table}


def multilabel_metrics(
    true_sets: Sequence[Sequence[str]],
    pred_sets: Sequence[Sequence[str]],
    labels: Sequence[str],
    scores: Sequence[dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Per-label P/R/F1 with micro and macro averages. Zero-support labels: support only."""
    per: dict[str, Any] = {}
    totals = np.zeros(3, dtype=int)
    macro: list[float] = []
    for label in labels:
        y = np.array([label in t for t in true_sets], bool)
        p = np.array([label in t for t in pred_sets], bool)
        support = int(y.sum())
        if support == 0:
            per[label] = {"support": 0, "predicted": int(p.sum()), "metrics": "omitted"}
            continue
        m = binary_metrics(y, p)
        c = m["confusion"]
        totals += [c["tp"], c["fp"], c["fn"]]
        row = {k: m[k] for k in ("precision", "recall", "f1")} | {
            "support": support, "predicted": int(p.sum()), "confusion": c,
        }  # fmt: skip
        if scores is not None:
            s = np.array([d.get(label, np.nan) for d in scores], float)
            if not np.isnan(s).any():
                row |= ranking_metrics(y, s)
        per[label] = row
        macro.append(row["f1"] or 0.0)
    tp, fp, fn = totals
    mp, mr = _div(tp, tp + fp), _div(tp, tp + fn)
    return {
        "per_label": per,
        "micro": {"precision": mp, "recall": mr, "f1": _f1(mp, mr)},
        "macro_f1": float(np.mean(macro)) if macro else None,
    }


def severity_metrics(true: pd.Series, pred: pd.Series) -> dict[str, Any]:
    """On true-issue rows with known severity and a predicted severity only."""
    mask = true.notna() & pred.notna()
    t = true[mask].astype(float).to_numpy()
    p = pred[mask].astype(float).to_numpy()
    out: dict[str, Any] = {"n": int(mask.sum()), "excluded": int((~mask).sum())}
    if len(t) < 3:
        return out
    rounded = np.clip(np.rint(p), 1, 5).astype(int)
    with warnings.catch_warnings():  # constant input -> NaN, reported as None below
        warnings.simplefilter("ignore")
        rho = spearmanr(t, p).statistic
        tau = kendalltau(t, p).statistic
    confusion = pd.crosstab(
        pd.Categorical(t.astype(int), range(1, 6)), pd.Categorical(rounded, range(1, 6)),
        dropna=False,
    )  # fmt: skip
    out |= {
        "spearman": None if np.isnan(rho) else float(rho),
        "kendall": None if np.isnan(tau) else float(tau),
        "mae": float(np.abs(t - p).mean()),
        "mae_rounded": float(np.abs(t - rounded).mean()),
        "exact_rounded": float((t == rounded).mean()),
        "confusion_true_rows_pred_cols": confusion.to_numpy().tolist(),
        "by_true_severity": {
            int(s): {"n": int((t == s).sum()), "mean_pred": float(p[t == s].mean())}
            for s in np.unique(t)
        },
    }
    return out


def operating_points(
    fit_y: np.ndarray, fit_s: np.ndarray, y: np.ndarray, s: np.ndarray, params: EvalParams
) -> list[dict[str, Any]]:
    """Fit each target's threshold on the fit set (val), then apply it to the eval set."""
    rows = []
    for target in params.precision_targets:
        fitted = recall_at_precision(fit_y, fit_s, target, params.grid)
        rows.append({"fit": fitted.to_dict(), "eval": apply_threshold(y, s, fitted).to_dict()})
    return rows


def bootstrap_by_game(
    df: pd.DataFrame,
    stat: Callable[[pd.DataFrame], dict[str, float | None]],
    samples: int,
    seed: int,
) -> dict[str, dict[str, float | None]]:
    """95% percentile CIs, resampling whole games with replacement."""
    groups = [g for _, g in df.groupby("game_id")]
    rng = np.random.default_rng(seed)
    draws: dict[str, list[float]] = {}
    for _ in range(samples):
        pick = rng.integers(0, len(groups), len(groups))
        for name, value in stat(pd.concat([groups[i] for i in pick])).items():
            if value is not None:
                draws.setdefault(name, []).append(value)
    point = stat(df)
    return {
        name: {
            "point": point.get(name),
            "lo": float(np.percentile(v, 2.5)) if v else None,
            "hi": float(np.percentile(v, 97.5)) if v else None,
            "valid_samples": len(v),
        }
        for name, v in draws.items()
    }


def slices(df: pd.DataFrame) -> dict[str, Any]:
    """Binary errors by game, source, true severity, crew class, weather, stitching/miscal."""

    def summary(part: pd.DataFrame) -> dict[str, Any]:
        m = binary_metrics(part["y"].to_numpy(), part["pred"].to_numpy())
        return {k: m[k] for k in ("n", "positives", "precision", "recall")} | m["confusion"]

    def has(c: str) -> pd.Series:
        return df["true_crew"].map(lambda cs: c in cs)

    out: dict[str, Any] = {
        "by_game": {g: summary(p) for g, p in df.groupby("game_id")},
        "by_source": {s: summary(p) for s, p in df.groupby("source")},
        "by_true_severity": {
            str(int(s)): summary(p) for s, p in df[df["true_severity"].notna()]
            .groupby("true_severity")
        },  # fmt: skip
        "by_crew_class": {
            c: summary(df[has(c)])
            for c in sorted({c for cs in df["true_crew"] for c in cs})
        },
        "weather_related": summary(df[df["weather_related"]]) if df["weather_related"].any()
        else None,
    }  # fmt: skip
    stitch = has("stitching_black_patch") | has("miscalibration")
    out["stitching_or_miscalibration"] = summary(df[stitch]) if stitch.any() else None
    return out


def _headline(df: pd.DataFrame, fitted: OperatingPoint | None) -> dict[str, float | None]:
    """Statistics that get bootstrap CIs."""
    y, pred = df["y"].to_numpy(bool), df["pred"].to_numpy(bool)
    m = binary_metrics(y, pred)
    out = {"precision": m["precision"], "recall": m["recall"], "f1": m["f1"]}
    if has_scores(df["score"]):
        s = df["score"].to_numpy(float)
        out |= {"average_precision": ranking_metrics(y, s)["average_precision"]}
        if fitted is not None and fitted.threshold is not None:
            op = apply_threshold(y, s, fitted)
            out |= {"op_precision": op.precision, "op_recall": op.recall}
    return out


def evaluate_table(
    df: pd.DataFrame,
    fit_df: pd.DataFrame,
    params: EvalParams,
    term_labels: Sequence[str],
    crew_labels: Sequence[str],
    fit_is_eval: bool,
    subsets: bool = True,
) -> dict[str, Any]:
    """Compute every section-7 metric for one prediction table.

    `fit_df` (the val split) supplies operating-point thresholds. When it is the same data
    as `df`, operating points are fit-and-evaluate on val and flagged as optimistic.
    """
    y, pred = df["y"].to_numpy(bool), df["pred"].to_numpy(bool)
    scored = has_scores(df["score"]) and has_scores(fit_df["score"])
    out: dict[str, Any] = {
        "n_images": len(df),
        "n_games": int(df["game_id"].nunique()),
        "parse_failures": {
            "count": int(df["parse_failed"].sum()),
            "rate": float(df["parse_failed"].mean()) if len(df) else None,
        },
        "binary_at_model_decision": binary_metrics(y, pred),
        "has_scores": scored,
        "operating_points_fit_on": "val (same data as eval: optimistic)" if fit_is_eval
        else "val",
    }  # fmt: skip
    selection = None
    if scored:
        s = df["score"].to_numpy(float)
        fy, fs = fit_df["y"].to_numpy(bool), fit_df["score"].to_numpy(float)
        out["ranking"] = ranking_metrics(y, s)
        out["calibration"] = calibration(y, s, params.confidence_bins)
        out["operating_points"] = operating_points(fy, fs, y, s, params)
        selection = recall_at_precision(fy, fs, params.selection_target, params.grid)
        out["pr_curve"] = pr_curve(y, s)
    out["bootstrap_95ci_by_game"] = bootstrap_by_game(
        df, lambda d: _headline(d, selection), params.bootstrap_samples, params.seed
    )
    has_defects = df["pred_terms"].map(len).sum() > 0 or df["term_scores"].map(bool).any()
    out["has_defect_predictions"] = bool(has_defects)
    if has_defects:
        term_scores = list(df["term_scores"]) if df["term_scores"].map(bool).all() else None
        crew_scores = list(df["crew_scores"]) if df["crew_scores"].map(bool).all() else None
        out["terms"] = multilabel_metrics(df["true_terms"], df["pred_terms"], term_labels,
                                          term_scores)  # fmt: skip
        out["crew_classes"] = multilabel_metrics(df["true_crew"], df["pred_crew"], crew_labels,
                                                 crew_scores)  # fmt: skip
        if term_scores is not None:
            out["term_operating_points"] = _label_operating_points(
                df, fit_df, "term_scores", "true_terms", term_labels, params
            )
    issue = df[df["y"]]
    sev_col = "severity_score" if has_scores(issue.get("severity_score", pd.Series([]))) \
        else "pred_severity"  # fmt: skip
    out["severity"] = severity_metrics(issue["true_severity"], issue[sev_col]) | {
        "predicted_from": sev_col
    }
    out["slices"] = slices(df)
    if subsets:
        user = df[df["source"] == "user"]
        if len(user) and user["y"].any() and (~user["y"]).any():
            out["user_subset"] = evaluate_table(
                user, fit_df, params, term_labels, crew_labels, fit_is_eval, subsets=False
            )
            out["user_subset"]["note"] = (
                "Operating thresholds are fit on all val rows, not only user rows."
            )
    return out


def _label_operating_points(
    df: pd.DataFrame,
    fit_df: pd.DataFrame,
    score_col: str,
    truth_col: str,
    labels: Sequence[str],
    params: EvalParams,
) -> dict[str, Any]:
    """Per-defect precision-first thresholds fit on val, applied to the eval split."""
    if not fit_df[score_col].map(bool).all() or not df[score_col].map(bool).all():
        return {}
    out = {}
    for label in labels:
        fy = fit_df[truth_col].map(lambda t, x=label: x in t).to_numpy(bool)
        y = df[truth_col].map(lambda t, x=label: x in t).to_numpy(bool)
        if not fy.any() or not y.any():
            continue
        fs = fit_df[score_col].map(lambda d, x=label: d.get(x, np.nan)).to_numpy(float)
        s = df[score_col].map(lambda d, x=label: d.get(x, np.nan)).to_numpy(float)
        if np.isnan(fs).any() or np.isnan(s).any():
            continue
        out[label] = operating_points(fy, fs, y, s, params)
    return out
