import numpy as np
import pytest

from streamsense.eval.thresholds import apply_threshold, recall_at_precision

Y = np.array([1, 1, 0, 1, 0, 0, 1, 0], bool)
S = np.array([0.95, 0.9, 0.85, 0.8, 0.6, 0.4, 0.3, 0.1])


def test_max_recall_subject_to_precision():
    op = recall_at_precision(Y, S, 0.75)
    # >= 0.8 predicts 4 with 3 TP: precision 0.75, recall 0.75.
    assert op.attainable and op.threshold == 0.8
    assert op.precision == pytest.approx(0.75) and op.recall == pytest.approx(0.75)


def test_perfect_precision_target():
    op = recall_at_precision(Y, S, 1.0)
    assert op.threshold == 0.9 and op.recall == pytest.approx(0.5)


def test_unattainable_target_is_reported_not_faked():
    y = np.array([0, 1, 0, 1], bool)
    s = np.array([0.9, 0.5, 0.8, 0.4])
    op = recall_at_precision(y, s, 0.9)
    assert not op.attainable and op.threshold is None and op.n_predicted == 0


def test_ties_keep_the_higher_threshold():
    y = np.array([1, 0, 0], bool)
    s = np.array([0.9, 0.2, 0.1])
    assert recall_at_precision(y, s, 1.0).threshold == 0.9


def test_grid_search_only_uses_grid_values():
    assert recall_at_precision(Y, S, 0.75, grid=[0.5, 0.75]).threshold == 0.75


def test_apply_fitted_threshold_to_new_data():
    fitted = recall_at_precision(Y, S, 1.0)
    y2 = np.array([1, 0, 1], bool)
    s2 = np.array([0.95, 0.92, 0.2])
    op = apply_threshold(y2, s2, fitted)
    assert op.threshold == 0.9 and op.precision == 0.5 and op.recall == 0.5


def test_length_mismatch_fails():
    with pytest.raises(ValueError):
        recall_at_precision(Y, S[:3], 0.9)
