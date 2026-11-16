import json
from pathlib import Path

import pytest

from streamsense.models.registry import REGISTRY, build_adapter
from streamsense.utils.run_record import recorded_run

MODEL_CONFIGS = sorted(
    p.stem for p in (Path(__file__).parents[1] / "conf" / "model").glob("*.yaml")
)


def test_every_model_config_has_a_registry_entry():
    assert set(MODEL_CONFIGS) == set(REGISTRY)


def test_unknown_model_is_rejected(make_cfg):
    cfg = make_cfg("model.name=not_registered")
    with pytest.raises(ValueError, match="Unknown model"):
        build_adapter(cfg)


def test_every_registry_entry_resolves_to_an_adapter():
    from importlib import import_module

    from streamsense.models.base import ModelAdapter

    for spec in REGISTRY.values():
        module, name = spec.import_path.split(":")
        assert issubclass(getattr(import_module(module), name), ModelAdapter)


def test_run_record_completes(make_cfg):
    cfg = make_cfg()
    with recorded_run(cfg, "unit") as run:
        run.record["extra"] = 1
    record = json.loads((run.output_dir / "run_record.json").read_text())
    assert record["status"] == "completed"
    assert record["seed"] == cfg.seed
    assert record["extra"] == 1
    assert record["wall_time_s"] >= 0
    assert (run.output_dir / ".hydra" / "resolved.yaml").exists()


def test_run_record_marks_failure(make_cfg):
    cfg = make_cfg()
    with pytest.raises(RuntimeError), recorded_run(cfg, "unit") as run:
        raise RuntimeError("boom")
    record = json.loads((run.output_dir / "run_record.json").read_text())
    assert record["status"] == "failed"
    assert record["error"] == {"type": "RuntimeError", "message": "boom"}
