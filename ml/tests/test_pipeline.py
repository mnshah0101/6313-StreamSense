"""E-00 on CPU: synthetic data -> split -> tiny CNN -> predictions -> shared metrics."""

import json
from pathlib import Path

import pytest

pytest.importorskip("torch")
pytest.importorskip("sklearn")

from streamsense.data.synthetic import synthetic_config  # noqa: E402
from streamsense.eval.predict import read_predictions  # noqa: E402
from streamsense.train.runner import run_evaluation, run_training  # noqa: E402
from streamsense.utils.run_record import recorded_run  # noqa: E402


def test_e00_smoke_end_to_end_on_cpu(make_cfg):
    cfg = make_cfg("+experiment=e00_smoke", "hardware.device=cpu", "logging.tensorboard=false")
    with recorded_run(cfg, "train") as run:
        cfg = synthetic_config(cfg, run.output_dir)
        metrics = run_training(cfg, run)
    assert metrics["split"] == "val" and metrics["has_scores"]
    record = json.loads((run.output_dir / "run_record.json").read_text())
    assert record["status"] == "completed" and record["locked_test_sha256"]
    for split in ("val", "test"):
        preds = read_predictions(run.output_dir, split)
        output, _ = next(iter(preds.values()))
        assert set(output) == {"quality_issue", "issues", "severity", "explanation",
                               "confidence", "metadata"}  # fmt: skip
    assert (run.output_dir / "eval_val" / "metrics.md").exists()
    assert (run.output_dir / "adapter" / "cnn.pt").exists()

    # Test evaluation is refused without the explicit final-test flag.
    with pytest.raises(ValueError, match="final_test"):
        from streamsense.config import validate_config

        validate_config(make_cfg("eval.split=test"))

    final = cfg.copy()
    final.eval.split, final.eval.final_test, final.eval.run_dir = "test", True, str(run.output_dir)
    with recorded_run(final, "evaluate") as ev:
        result = run_evaluation(final, ev)
    assert result["split"] == "test" and result["locked_test_sha256"]


def test_finished_run_is_mirrored_to_local_mlflow(make_cfg):
    from mlflow.tracking import MlflowClient

    cfg = make_cfg("+experiment=e00_smoke", "hardware.device=cpu", "logging.tensorboard=false")
    with recorded_run(cfg, "train") as run:
        run_training(synthetic_config(cfg, run.output_dir), run)
    client = MlflowClient(tracking_uri=cfg.logging.mlflow_uri)
    exp = client.get_experiment_by_name("E-00")
    runs = client.search_runs([exp.experiment_id])
    assert len(runs) == 1 and runs[0].info.status == "FINISHED"
    assert "val_ap" in runs[0].data.metrics and runs[0].data.params["model.name"] == "cnn_resnet18"
    assert runs[0].data.tags["run_dir"] == str(run.output_dir.resolve())
    from streamsense.utils.tracking import log_run_dir

    again = log_run_dir(run.output_dir, cfg.logging.mlflow_uri, Path(cfg.logging.mlflow_artifacts))
    assert again == runs[0].info.run_id  # idempotent
