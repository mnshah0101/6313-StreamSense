import json

import pandas as pd
import pytest

from streamsense.data import taxonomy as tx
from streamsense.data.ingest import build_rows, extract_archive, ingest, training_rows
from streamsense.data.prepare import prepare
from streamsense.data.split import SplitLockError
from streamsense.data.synthetic import synthetic_labels, write_synthetic_archive

DECISIONS = {"valid": "positive", "not": "negative", "duplicate": "drop"}
KNOWN = {"decision", "source", "term", "updated_at", "description", "severity"}


@pytest.fixture
def tax(make_cfg):
    return tx.Taxonomy.from_config(make_cfg().taxonomy)


def keys(labels):
    return frozenset(k for k, v in labels.items() if v["decision"] != "duplicate")


def test_rows_drop_duplicates_and_missing_images(tax):
    labels = synthetic_labels()
    present = keys(labels) - {"synthetic_game_c/frame_01.jpg"}
    rows, dropped = build_rows(labels, tax, DECISIONS, KNOWN, present)
    assert dropped == {"duplicate": 1, "missing_image": 1}
    by_key = {r["key"]: r for r in rows}
    assert set(by_key) == present
    first = by_key["synthetic_game_a/frame_01.jpg"]
    assert first["quality_issue"] and first["terms"] == ["blur", "overexposure"]
    assert first["crew_classes"] == ["blur_lens_smear", "overexposure"]
    assert first["game_id"] == "synthetic_game_a" and first["frame_idx"] == 1
    fog = by_key["synthetic_game_b/frame_01.jpg"]
    assert fog["weather_related"] and fog["severity"] is None
    assert not by_key["synthetic_game_a/frame_02.jpg"]["quality_issue"]


def test_unknown_fields_are_kept_in_extra(tax):
    labels = synthetic_labels()
    labels["synthetic_game_a/frame_01.jpg"]["reviewer"] = "x"
    rows, _ = build_rows(labels, tax, DECISIONS, KNOWN, keys(labels))
    extra = {r["key"]: json.loads(r["extra"]) for r in rows}
    assert extra["synthetic_game_a/frame_01.jpg"] == {"reviewer": "x"}


def test_training_policies_touch_train_rows_only(make_cfg):
    df = pd.DataFrame({
        "quality_issue": [True, True, False],
        "severity": pd.array([3, None, None], dtype="Int64"),
        "source": ["user", "prefill", "user"],
    })  # fmt: skip
    kept, counts = training_rows(df, make_cfg().labels)
    assert len(kept) == 3 and counts == {"severity_missing_mask": 1}
    kept, counts = training_rows(df, make_cfg("labels.severity_missing=drop_row").labels)
    assert len(kept) == 2
    kept, counts = training_rows(df, make_cfg("labels.source_filter=user_only").labels)
    assert list(kept["source"]) == ["user", "user"] and counts["source_filter_dropped"] == 1


def test_extract_is_idempotent(make_cfg, synthetic_root, tmp_path):
    archive = write_synthetic_archive(synthetic_root, tmp_path / "v1.zip")
    cfg = make_cfg(f"data.zip_path={archive}", f"data.extract_dir={tmp_path / 'x'}")
    digest = extract_archive(cfg)
    marker_time = (tmp_path / "x" / ".streamsense_extracted.json").stat().st_mtime_ns
    assert extract_archive(cfg) == digest
    assert (tmp_path / "x" / ".streamsense_extracted.json").stat().st_mtime_ns == marker_time
    assert (tmp_path / "x" / "partition_1" / "labels.json").exists()


def fixture_cfg(make_cfg, root, tmp_path, *extra):
    return make_cfg(
        "data.input_mode=extracted", f"data.extract_dir={root}", "data.root_subdir=",
        f"split.manifest_path={tmp_path / 'splits' / 'split.json'}",
        f"split.locked_test_path={tmp_path / 'splits' / 'LOCKED.json'}", *extra,
    )  # fmt: skip


def test_ingest_hashes_and_prepare_locks(make_cfg, tmp_path):
    from streamsense.data.synthetic import write_synthetic_study

    root = write_synthetic_study(tmp_path / "study", seed=0)
    cfg = fixture_cfg(make_cfg, root, tmp_path)
    ing = ingest(cfg)
    assert (
        len(ing.manifest)
        == ing.inspection.summary["counts"]["decision"]["valid"]
        + (ing.inspection.summary["counts"]["decision"]["not"])
    )
    assert ing.manifest["image_sha256"].str.len().eq(64).all()
    first = prepare(cfg)
    assert first.lock is not None
    assert prepare(cfg).split.games == first.split.games  # reused, not regenerated
    labels = json.loads((root / "labels.json").read_text())
    test_key = next(k for k in first.lock["test_keys"])
    labels[test_key]["decision"] = "valid" if labels[test_key]["decision"] == "not" else "not"
    labels[test_key]["term"] = "blur" if labels[test_key]["decision"] == "valid" else ""
    labels[test_key].pop("severity", None)
    (root / "labels.json").write_text(json.dumps(labels))
    with pytest.raises(SplitLockError, match="Manifest changed"):
        prepare(cfg)
