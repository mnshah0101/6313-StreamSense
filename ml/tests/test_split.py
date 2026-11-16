import pandas as pd
import pytest

from streamsense.data import split as sp

RATIOS = {"train": 0.7, "val": 0.15, "test": 0.15}


def manifest(n_games=20, frames=5):
    rows = []
    for g in range(n_games):
        for f in range(frames):
            pos = (g + f) % 2 == 0
            rows.append({
                "key": f"g{g:02d}/frame_{f:02d}.jpg", "game_id": f"g{g:02d}",
                "quality_issue": pos, "crew_classes": ["blur_lens_smear"] if pos else [],
                "decision": "valid" if pos else "not", "source": "user",
                "severity": pd.NA, "image_sha256": f"sha{g}-{f}",
            })  # fmt: skip
    return pd.DataFrame(rows)


def make(m, locked=None, seed=0, classes=("blur_lens_smear",)):
    return sp.make_split(m, RATIOS, seed, 300, list(classes), "h", locked)


def test_split_is_by_game_and_complete():
    m = manifest()
    s = make(m)
    sp.check_no_leakage(m, s)
    games = [g for v in s.games.values() for g in v]
    assert len(games) == len(set(games)) == 20
    assert len(s.games["train"]) > len(s.games["val"]) > 0 and s.games["test"]


def test_split_is_deterministic_for_a_seed():
    m = manifest()
    assert make(m, seed=3).games == make(m, seed=3).games


def test_identical_images_keep_games_together():
    m = manifest()
    m.loc[m["key"].isin(["g05/frame_00.jpg", "g11/frame_00.jpg"]), "image_sha256"] = "same"
    assert ("g05", "g11") in sp.game_components(m)
    assert sp.cross_game_duplicates(m) == [("g05/frame_00.jpg", "g11/frame_00.jpg")]
    for seed in range(5):
        s = make(m, seed=seed)
        sp.check_no_leakage(m, s)
        part = s.assign(m)
        assert part[m["game_id"] == "g05"].iloc[0] == part[m["game_id"] == "g11"].iloc[0]


def test_leakage_check_catches_overlap():
    m = manifest()
    s = make(m)
    bad = sp.Split({**s.games, "val": (*s.games["val"], s.games["test"][0])}, "h", 0)
    with pytest.raises(sp.SplitLockError):
        sp.check_no_leakage(m, bad)


def test_locked_test_games_stay_in_test(tmp_path):
    m = manifest()
    first = make(m, seed=0)
    lock = tmp_path / "LOCKED_TEST.json"
    sp.write_lock(lock, first, m, tmp_path / "split.json")
    with pytest.raises(sp.SplitLockError, match="overwrite"):
        sp.write_lock(lock, first, m, tmp_path / "split.json")
    second = make(m, locked=tuple(sp.read_json_games(lock)), seed=7)
    assert second.games["test"] == first.games["test"]
    sp.verify_lock(lock, second, m)


def test_lock_detects_changed_test_images(tmp_path):
    m = manifest()
    s = make(m)
    lock = tmp_path / "LOCKED_TEST.json"
    sp.write_lock(lock, s, m, tmp_path / "split.json")
    changed = m[m["key"] != f"{s.games['test'][0]}/frame_00.jpg"]
    with pytest.raises(sp.SplitLockError, match="differ"):
        sp.verify_lock(lock, s, changed)


def test_rare_class_is_covered_in_every_split_when_possible():
    m = manifest(n_games=30)
    rare = m["game_id"].isin(["g01", "g02", "g03", "g04"])
    m["crew_classes"] = [["weather"] if r else [] for r in rare]
    s = make(m, classes=("weather",))
    assert set(s.assign(m)[rare]) == {"train", "val", "test"}
