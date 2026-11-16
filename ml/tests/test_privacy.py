import json
import subprocess

import pytest
from omegaconf import OmegaConf

from streamsense.data.synthetic import synthetic_labels
from streamsense.privacy import content_violation, path_violation, staged_violations


@pytest.fixture
def policy(make_cfg):
    return OmegaConf.to_object(make_cfg().privacy)


@pytest.mark.parametrize(
    "name",
    [
        "data/anything.txt",
        "outputs/E-01/run_record.json",
        "splits/LOCKED_TEST.json",
        "docs/DATA_SCHEMA.md",
        "labels.json",
        "nested/game/frame_01.JPG",
        "partition.zip",
        "model.safetensors",
        "manifest.parquet",
        "wandb/run.log",
    ],
)
def test_private_paths_are_blocked(policy, name):
    assert path_violation(name, policy, None) is not None


@pytest.mark.parametrize(
    "name",
    [
        "streamsense/config.py",
        "conf/config.yaml",
        "docs/DATA_SCHEMA_TEMPLATE.md",
        "streamsense/data/ingest.py",
        "conf/data/taxonomy.yaml",
    ],
)
def test_source_paths_are_allowed(policy, name):
    assert path_violation(name, policy, None) is None


def test_configured_labels_filename_is_blocked(policy):
    assert path_violation("docs/client_labels.json", policy, "client_labels.json")


@pytest.mark.parametrize(
    "blob",
    [
        b"\xff\xd8\xff\xe0jpeg",
        b"\x89PNG\r\n\x1a\nrest",
        b"PK\x03\x04zip",
        b"\x1f\x8bgz",
        b"RIFF\x00\x00\x00\x00WEBP",
    ],
)
def test_binary_signatures_are_blocked(blob):
    assert content_violation(blob, scan_json=True)


def test_label_json_content_is_blocked_under_any_name():
    blob = json.dumps(synthetic_labels()).encode()
    assert content_violation(blob, scan_json=True)
    assert content_violation(blob, scan_json=False) is None
    assert content_violation(b'{"name": "config"}', scan_json=True) is None


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_staged_violations_inspect_the_index(policy, tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "ok.py").write_text("x = 1\n")
    (tmp_path / "notes.txt").write_text(json.dumps(synthetic_labels()))
    (tmp_path / "frame.dat").write_bytes(b"\xff\xd8\xff\xe0jpeg")
    git(tmp_path, "add", "-f", "ok.py", "notes.txt", "frame.dat")
    found = dict(staged_violations(tmp_path, policy, None))
    assert set(found) == {"notes.txt", "frame.dat"}


def test_notebook_outputs_are_blocked_but_clean_source_passes():
    clean = {"cells": [{"cell_type": "code", "outputs": [], "execution_count": None,
                        "source": "x = 1"}], "nbformat": 4}  # fmt: skip
    executed = {"cells": [{"cell_type": "code", "outputs": [{"output_type": "stream"}],
                           "execution_count": 1, "source": "x"}], "nbformat": 4}  # fmt: skip
    assert content_violation(json.dumps(clean).encode(), scan_json=True) is None
    assert content_violation(json.dumps(executed).encode(), scan_json=True)
