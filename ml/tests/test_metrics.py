import numpy as np
import pandas as pd
import pytest

from streamsense.eval import metrics as mt


def test_binary_metrics_confusion():
    y = np.array([1, 1, 0, 0, 1], bool)
    p = np.array([1, 0, 1, 0, 1], bool)
    m = mt.binary_metrics(y, p)
    assert m["confusion"] == {"tp": 2, "fp": 1, "fn": 1, "tn": 1}
    assert m["precision"] == pytest.approx(2 / 3) and m["recall"] == pytest.approx(2 / 3)
    assert m["accuracy"] == pytest.approx(0.6)


def test_binary_metrics_no_predictions_is_undefined_not_zero():
    m = mt.binary_metrics(np.array([1, 0], bool), np.array([0, 0], bool))
    assert m["precision"] is None and m["recall"] == 0.0


def test_ranking_undefined_with_one_class():
    assert mt.ranking_metrics(np.array([1, 1], bool), np.array([0.2, 0.9])) == {
        "average_precision": None,
        "roc_auc": None,
        "log_loss": None,
    }
    r = mt.ranking_metrics(np.array([0, 1], bool), np.array([0.2, 0.9]))
    assert r["average_precision"] == 1.0 and r["roc_auc"] == 1.0


def test_calibration_ece():
    y = np.array([0, 0, 1, 1])
    assert mt.calibration(y, np.array([0.0, 0.0, 1.0, 1.0]), 10)["ece"] == 0.0
    assert mt.calibration(y, np.array([0.5] * 4), 10)["ece"] == pytest.approx(0.0)
    assert mt.calibration(np.array([1, 1]), np.array([0.25, 0.25]), 4)["ece"] == 0.75


def test_multilabel_omits_zero_support_and_averages():
    true = [("a",), ("a", "b"), ()]
    pred = [("a",), ("b",), ("b",)]
    m = mt.multilabel_metrics(true, pred, ["a", "b", "c"])
    assert m["per_label"]["c"] == {"support": 0, "predicted": 0, "metrics": "omitted"}
    assert m["per_label"]["a"]["precision"] == 1.0 and m["per_label"]["a"]["recall"] == 0.5
    assert m["per_label"]["b"]["precision"] == 0.5 and m["per_label"]["b"]["recall"] == 1.0
    assert m["micro"]["precision"] == pytest.approx(2 / 3)
    assert m["macro_f1"] == pytest.approx(2 / 3)


def test_severity_metrics_skip_unknown():
    true = pd.Series([1, 2, 3, 4, 5, np.nan])
    pred = pd.Series([1.2, 2.1, 2.9, 4.4, 4.8, 3.0])
    m = mt.severity_metrics(true, pred)
    assert m["n"] == 5 and m["excluded"] == 1
    assert m["spearman"] == pytest.approx(1.0) and m["exact_rounded"] == 1.0
    assert m["confusion_true_rows_pred_cols"][0][0] == 1


def table(n_games=6, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_games):
        for i in range(4):
            y = bool(i % 2)
            s = float(np.clip(0.5 + (0.3 if y else -0.3) + rng.normal(0, 0.2), 0, 1))
            hit = s >= 0.5
            rows.append({
                "key": f"g{g}/frame_{i:02d}.jpg", "game_id": f"g{g}",
                "source": "user" if i < 2 else "prefill", "y": y, "pred": hit,
                "score": s, "parse_failed": False,
                "true_terms": ("blur",) if y else (), "pred_terms": ("blur",) if hit else (),
                "true_crew": ("blur_lens_smear",) if y else (),
                "pred_crew": ("blur_lens_smear",) if hit else (),
                "true_severity": 3.0 if y else np.nan, "pred_severity": 3.0 if hit else np.nan,
                "severity_score": 3.0, "term_scores": {"blur": s},
                "crew_scores": {"blur_lens_smear": s}, "weather_related": False,
            })  # fmt: skip
    return pd.DataFrame(rows)


PARAMS = mt.EvalParams((0.9,), 0.9, bootstrap_samples=20, confidence_bins=5, seed=0)


def test_evaluate_table_end_to_end():
    df = table()
    r = mt.evaluate_table(df, df, PARAMS, ["blur", "other"], ["blur_lens_smear", "other"], True)
    assert r["n_images"] == 24 and r["n_games"] == 6
    assert r["has_scores"] and "optimistic" in r["operating_points_fit_on"]
    assert r["terms"]["per_label"]["other"]["metrics"] == "omitted"
    assert set(r["slices"]["by_game"]) == {f"g{g}" for g in range(6)}
    assert "user_subset" in r
    ci = r["bootstrap_95ci_by_game"]["precision"]
    assert ci["lo"] <= ci["point"] <= ci["hi"]


def test_operating_point_is_fit_on_val_and_applied_to_eval():
    val, test = table(seed=0), table(seed=1)
    r = mt.evaluate_table(test, val, PARAMS, ["blur"], ["blur_lens_smear"], False, False)
    op = r["operating_points"][0]
    assert r["operating_points_fit_on"] == "val"
    assert op["eval"]["threshold"] == op["fit"]["threshold"]


def test_models_without_scores_skip_score_metrics():
    df = table().assign(score=np.nan, term_scores=[{}] * 24, crew_scores=[{}] * 24)
    r = mt.evaluate_table(df, df, PARAMS, ["blur"], ["blur_lens_smear"], True, False)
    assert not r["has_scores"] and "operating_points" not in r
    assert r["terms"]["per_label"]["blur"]["support"] == 12


def test_parse_failures_are_counted():
    df = table()
    df.loc[0, "parse_failed"] = True
    r = mt.evaluate_table(df, df, PARAMS, ["blur"], ["blur_lens_smear"], True, subsets=False)
    assert r["parse_failures"]["count"] == 1


def test_bootstrap_resamples_whole_games():
    df = table(n_games=3)
    seen = []

    def stat(d):
        seen.append(d.groupby("game_id").size().tolist())
        return {"x": 1.0}

    mt.bootstrap_by_game(df, stat, samples=10, seed=0)
    assert all(all(s % 4 == 0 for s in sizes) for sizes in seen)
