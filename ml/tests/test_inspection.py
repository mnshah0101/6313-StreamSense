import copy
import json

import pytest
from omegaconf import OmegaConf

from streamsense.config import LabelConfig, UnknownFields
from streamsense.data.inspection import (
    LabelSchemaError,
    inspect_dataset,
    inspect_labels,
    read_label_input,
)
from streamsense.data.synthetic import synthetic_labels, write_synthetic_archive
from streamsense.utils.io import load_strict_json
from streamsense.utils.run_record import RunContext


@pytest.fixture
def policy(make_cfg) -> LabelConfig:
    return OmegaConf.to_object(make_cfg().labels)


def checks(result, name):
    return [f for f in result.findings if f.check == name]


def image_keys(labels):
    return frozenset(k for k, v in labels.items() if v["decision"] != "duplicate")


def test_synthetic_labels_are_clean(policy):
    labels = synthetic_labels()
    result = inspect_labels(labels, policy, image_keys(labels))
    assert result.fatal_count == 0
    s = result.summary
    assert s["rows"] == 5
    assert s["counts"]["decision"] == {"duplicate": 1, "not": 2, "valid": 2}
    assert s["counts"]["term"] == {"blur": 2, "fog": 1, "overexposure": 1}
    assert s["counts"]["positive_term"] == {"blur": 1, "fog": 1, "overexposure": 1}
    assert s["counts"]["severity"] == {"(missing)": 4, "3": 1}
    assert s["games_in_labels"] == 3
    assert s["games_with_nonduplicate_labels"] == 3


def test_term_string_is_split_stripped_and_lowercased(policy):
    labels = {
        "g/frame_01.jpg": {
            "decision": "valid",
            "term": " Blur ,LENS FLARE,, ",
            "severity": 2,
            "source": "user",
            "updated_at": "t",
        }
    }
    result = inspect_labels(labels, policy)
    assert result.summary["counts"]["term"] == {"blur": 1, "lens flare": 1}


def test_duplicate_rows_are_audited_not_counted_as_games(policy):
    labels = synthetic_labels()
    result = inspect_labels(labels, policy, image_keys(labels))
    assert [f.key for f in checks(result, "duplicate_image_absent")] == [
        "synthetic_game_b/frame_02.jpg"
    ]
    assert len(checks(result, "duplicate_with_term")) == 1
    present = image_keys(labels) | {"synthetic_game_b/frame_02.jpg"}
    result = inspect_labels(labels, policy, present)
    assert len(checks(result, "duplicate_image_present")) == 1
    assert result.fatal_count == 0


def test_missing_severity_on_valid_is_reported_not_fatal(policy):
    labels = synthetic_labels()
    result = inspect_labels(labels, policy)
    missing = checks(result, "valid_missing_severity")
    assert [f.key for f in missing] == ["synthetic_game_b/frame_01.jpg"]
    assert not missing[0].fatal


def test_file_inventory_mismatches(policy):
    labels = synthetic_labels()
    keys = image_keys(labels) - {"synthetic_game_a/frame_01.jpg"} | {"extra/frame_09.jpg"}
    result = inspect_labels(labels, policy, keys)
    assert [f.key for f in checks(result, "nonduplicate_missing_image")] == [
        "synthetic_game_a/frame_01.jpg"
    ]
    assert [f.key for f in checks(result, "image_without_label")] == ["extra/frame_09.jpg"]
    assert result.fatal_count == 0


def mutate(key, **changes):
    labels = copy.deepcopy(synthetic_labels())
    for name, value in changes.items():
        if value is ...:
            labels[key].pop(name)
        else:
            labels[key][name] = value
    return labels


VALID = "synthetic_game_a/frame_01.jpg"
NEGATIVE = "synthetic_game_a/frame_02.jpg"


@pytest.mark.parametrize(
    ("labels", "check"),
    [
        (mutate(VALID, decision="maybe"), "unknown_decision"),
        (mutate(VALID, source="robot"), "unknown_source"),
        (mutate(VALID, updated_at=...), "missing_fields"),
        (mutate(VALID, reviewer="x"), "extra_fields"),
        (mutate(VALID, term=["blur"]), "invalid_term"),
        (mutate(VALID, description=3), "invalid_description"),
        (mutate(VALID, severity=0), "invalid_severity"),
        (mutate(VALID, severity=6), "invalid_severity"),
        (mutate(VALID, severity=2.5), "invalid_severity"),
        (mutate(VALID, severity="3"), "invalid_severity"),
        (mutate(VALID, severity=True), "invalid_severity"),
        (mutate(VALID, severity=None), "invalid_severity"),
        (mutate(VALID, term=""), "valid_empty_term"),
        (mutate(NEGATIVE, term="blur"), "negative_with_annotation"),
        (mutate(NEGATIVE, severity=2), "negative_with_annotation"),
    ],
)
def test_fatal_label_discrepancies(policy, labels, check):
    result = inspect_labels(labels, policy)
    assert any(f.check == check and f.fatal for f in result.findings)


@pytest.mark.parametrize(
    "key",
    ["game/frame_1.png", "frame_01.jpg", "a/b/frame_01.jpg", "../frame_01.jpg", "g/image_01.jpg"],
)
def test_invalid_keys_are_fatal(policy, key):
    labels = {key: synthetic_labels()[VALID]}
    result = inspect_labels(labels, policy)
    assert any(f.check == "invalid_key" and f.fatal for f in result.findings)


def test_unknown_fields_can_be_preserved_explicitly(policy):
    policy.unknown_fields = UnknownFields.preserve
    result = inspect_labels(mutate(VALID, reviewer="x"), policy)
    assert result.fatal_count == 0
    assert checks(result, "extra_fields")


@pytest.mark.parametrize("payload", [{}, [], "labels"])
def test_payload_must_be_nonempty_object(policy, payload):
    with pytest.raises(LabelSchemaError):
        inspect_labels(payload, policy)


def test_strict_json_rejects_duplicate_keys_and_nan():
    with pytest.raises(ValueError, match="Duplicate"):
        load_strict_json('{"a": 1, "a": 2}')
    with pytest.raises(ValueError, match="Non-finite"):
        load_strict_json('{"a": NaN}')


def test_reads_extracted_root(make_cfg, synthetic_root):
    cfg = make_cfg(
        "data.input_mode=extracted", f"data.extract_dir={synthetic_root}", "data.root_subdir="
    )
    source = read_label_input(cfg)
    assert source.payload == synthetic_labels()
    assert source.image_keys == image_keys(synthetic_labels())
    assert source.archive_sha256 is None


def test_reads_zip_without_extracting(make_cfg, synthetic_root, tmp_path):
    archive = write_synthetic_archive(synthetic_root, tmp_path / "data" / "v1.zip")
    cfg = make_cfg(f"data.zip_path={archive}")
    source = read_label_input(cfg)
    assert source.payload == synthetic_labels()
    assert source.image_keys == image_keys(synthetic_labels())
    assert source.archive_sha256 is not None
    assert not (tmp_path / "data" / "extracted").exists()


def test_label_autodetect_requires_exactly_one_json(make_cfg, synthetic_root):
    (synthetic_root / "other.json").write_text("{}")
    cfg = make_cfg(
        "data.input_mode=extracted", f"data.extract_dir={synthetic_root}", "data.root_subdir="
    )
    with pytest.raises(LabelSchemaError, match="exactly one"):
        read_label_input(cfg)
    cfg = make_cfg(
        "data.input_mode=extracted",
        f"data.extract_dir={synthetic_root}",
        "data.root_subdir=",
        "data.labels_file=labels.json",
    )
    assert read_label_input(cfg).payload == synthetic_labels()


@pytest.mark.parametrize("name", ["../labels.json", "/etc/labels.json", "labels.txt"])
def test_labels_file_must_stay_inside_root(make_cfg, synthetic_root, name):
    cfg = make_cfg(
        "data.input_mode=extracted",
        f"data.extract_dir={synthetic_root}",
        "data.root_subdir=",
        f"data.labels_file={name}",
    )
    with pytest.raises(LabelSchemaError):
        read_label_input(cfg)


def test_labels_size_limit(make_cfg, synthetic_root):
    cfg = make_cfg(
        "data.input_mode=extracted",
        f"data.extract_dir={synthetic_root}",
        "data.root_subdir=",
        "data.max_labels_bytes=10",
    )
    with pytest.raises(LabelSchemaError, match="max_labels_bytes"):
        read_label_input(cfg)


def test_inspect_dataset_writes_aggregate_report_only(make_cfg, synthetic_root, tmp_path):
    report = tmp_path / "DATA_SCHEMA.md"
    cfg = make_cfg(
        "data.input_mode=extracted",
        f"data.extract_dir={synthetic_root}",
        "data.root_subdir=",
        f"data.schema_report={report}",
    )
    run = RunContext(tmp_path / "run", {})
    inspect_dataset(cfg, run)
    text = report.read_text()
    assert "Open questions" in text
    assert "Synthetic test frame." not in text
    assert "synthetic_game_a" not in text
    summary = json.loads((tmp_path / "run" / "label_summary.json").read_text())
    assert summary["rows"] == 5
    assert (tmp_path / "run" / "label_findings.csv").exists()


def test_inspect_dataset_fails_on_fatal_findings(make_cfg, synthetic_root, tmp_path):
    labels = mutate(VALID, decision="maybe")
    (synthetic_root / "labels.json").write_text(json.dumps(labels))
    cfg = make_cfg(
        "data.input_mode=extracted",
        f"data.extract_dir={synthetic_root}",
        "data.root_subdir=",
        f"data.schema_report={tmp_path / 'r.md'}",
    )
    with pytest.raises(LabelSchemaError, match="fatal"):
        inspect_dataset(cfg, RunContext(tmp_path / "run", {}))
