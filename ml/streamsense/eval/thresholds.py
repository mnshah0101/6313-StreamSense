"""Precision-first operating points: maximize recall subject to precision >= target."""

from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class OperatingPoint:
    target_precision: float
    attainable: bool
    threshold: float | None  # predict positive when score >= threshold
    precision: float | None
    recall: float | None
    n_predicted: int

    def to_dict(self) -> dict:
        return asdict(self)


def candidates(scores: np.ndarray, grid: Sequence[float] | None = None) -> np.ndarray:
    """Exact search uses every distinct score; a grid is a coarser, config-listed option."""
    values = np.unique(scores) if grid is None else np.asarray(sorted(set(grid)), dtype=float)
    return values[::-1]


def recall_at_precision(
    y_true: np.ndarray, scores: np.ndarray, target: float, grid: Sequence[float] | None = None
) -> OperatingPoint:
    """Lowest-threshold point with precision >= target; ties keep the higher threshold.

    If no threshold reaches the target, the point is reported as unattainable instead of
    returning a zero-prediction threshold that would look like a valid operating point.
    """
    y = np.asarray(y_true, dtype=bool)
    s = np.asarray(scores, dtype=float)
    if len(y) != len(s):
        raise ValueError("y_true and scores must have the same length")
    best: OperatingPoint | None = None
    n_pos = int(y.sum())
    for t in candidates(s, grid):
        pred = s >= t
        n_pred = int(pred.sum())
        if n_pred == 0:
            continue
        tp = int((pred & y).sum())
        precision = tp / n_pred
        recall = tp / n_pos if n_pos else 0.0
        if precision >= target and (best is None or recall > best.recall):
            best = OperatingPoint(target, True, float(t), precision, recall, n_pred)
    return best or OperatingPoint(target, False, None, None, None, 0)


def apply_threshold(
    y_true: np.ndarray, scores: np.ndarray, point: OperatingPoint
) -> OperatingPoint:
    """Evaluate a threshold fitted elsewhere (val) on new data (e.g. test)."""
    if point.threshold is None:
        return OperatingPoint(point.target_precision, False, None, None, None, 0)
    y = np.asarray(y_true, dtype=bool)
    pred = np.asarray(scores, dtype=float) >= point.threshold
    n_pred, tp = int(pred.sum()), int((pred & y).sum())
    precision = tp / n_pred if n_pred else None
    recall = tp / int(y.sum()) if y.any() else None
    return OperatingPoint(
        point.target_precision, point.attainable, point.threshold, precision, recall, n_pred
    )
