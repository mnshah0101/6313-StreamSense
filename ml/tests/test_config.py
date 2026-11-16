from pathlib import Path

import pytest
from hydra.errors import ConfigCompositionException
from omegaconf.errors import ValidationError

from streamsense.config import validate_config

EXPERIMENTS = sorted(
    p.stem for p in (Path(__file__).parents[1] / "conf" / "experiment").glob("*.yaml")
)


@pytest.mark.parametrize("experiment", EXPERIMENTS)
def test_every_experiment_composes_and_validates(make_cfg, experiment):
    cfg = make_cfg(f"+experiment={experiment}")
    validate_config(cfg)
    assert cfg.experiment_id


def test_default_config_is_precision_first_and_private(make_cfg):
    cfg = make_cfg()
    validate_config(cfg)
    assert cfg.labels.decision_map["not"] == "negative"
    assert cfg.labels.duplicate_policy == "drop"
    assert cfg.eval.split == "val"
    assert not cfg.logging.cloud and not cfg.logging.upload_images


def test_unknown_key_fails_at_compose_time(make_cfg):
    with pytest.raises((ConfigCompositionException, ValidationError)):
        make_cfg("data.not_a_real_field=1")


def test_wrong_type_fails_at_compose_time(make_cfg):
    with pytest.raises((ConfigCompositionException, ValidationError)):
        make_cfg("data.image_size=large")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (["split.ratios.train=0.8"], "sum to 1"),
        (["labels.decision_map.not=positive"], "decision map"),
        (["labels.duplicate_policy=keep"], "Duplicate"),
        (["eval.split=test"], "final_test"),
        (["eval.precision_targets=[1.5]"], "Precision targets"),
        (["logging.cloud=true"], "Cloud logging"),
        (["logging.mlflow_uri=https://tracking.example.com"], "local"),
        (["model.revision=main"], "commit SHA"),
        (["taxonomy.mapping.blur.crew_class=not_a_class"], "crew class"),
        (["train.selection_metric=accuracy"], "recall"),
    ],
)
def test_validation_rejects_unsupported_semantics(make_cfg, overrides, message):
    cfg = make_cfg(*overrides)
    with pytest.raises(ValueError, match=message):
        validate_config(cfg)


def test_final_test_evaluation_is_explicit(make_cfg):
    validate_config(make_cfg("eval.split=test", "eval.final_test=true"))


def test_training_seed_does_not_change_the_split(make_cfg):
    a, b = make_cfg("seed=0"), make_cfg("seed=1")
    assert a.split.seed == b.split.seed == 42
    assert a.split.manifest_path == b.split.manifest_path
