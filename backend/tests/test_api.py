import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select, update

from app import db as dbm
from app.inference.dummy import DummyBackend
from app.models import Alert, Frame, Game, Job
from app.worker import Worker

from .conftest import analyze, fetch_media, jpeg, make_settings, mp4

THUMB_CACHE = "private, max-age=300"


def run_all(worker) -> None:
    while worker.run_once():
        pass


# ---- one-step analysis -------------------------------------------------------------------


def test_analysis_end_to_end(client, worker, tmp_path):
    """Upload + metadata -> game + queued job -> frames, stretches, alert, heat maps."""
    r = analyze(client, mp4(tmp_path / "m.mp4", seconds=20, size=(1280, 720), black_sec=4))
    assert r.status_code == 202, r.json()
    game, job = r.json()["game"], r.json()["job"]
    assert (game["home"], game["sport"], game["camera"], game["status"]) == (
        "Westview", "Soccer", "Pixellot", "queued")  # fmt: skip
    assert game["hasVideo"] and game["mediaKind"] == "video"
    assert job["status"] == "queued" and job["totalFrames"] == game["totalFrames"] == 4
    poster = Image.open(BytesIO(fetch_media(client, game["posterUrl"], THUMB_CACHE)))
    assert poster.size == (640, 360) and np.asarray(poster.convert("L")).mean() > 16  # not black

    run_all(worker)
    g = client.get(f"/games/{game['id']}").json()
    assert g["status"] == "analyzed" and g["analyzedFrames"] == 4
    frames = client.get(f"/games/{game['id']}/frames").json()
    assert [f["timestampMs"] for f in frames] == [0, 5000, 10000, 15000]
    # t=0 is in the black opening (Low light), t=5 s is clean, the second half is blurry.
    assert [f["qualityIssue"] for f in frames] == [True, False, True, True]
    assert "Low light" in [d["type"] for d in frames[0]["detections"]]
    # Only flagged frames get defects + explanation (generate="flagged").
    assert not frames[1]["detections"] and frames[1]["explanation"] is None
    assert frames[2]["detections"][0]["type"] == "Blur" and frames[2]["explanation"]
    # Short video: every flagged spatial frame has a heat map with the frame's exact size.
    for f in frames[2:]:
        assert (
            f["heatmap"]["status"] == "available" and f["heatmap"]["method"] == "dummy_low_detail"
        )
        img = Image.open(BytesIO(fetch_media(client, f["imageUrl"])))
        ov = Image.open(BytesIO(fetch_media(client, f["heatmap"]["overlayUrl"])))
        assert ov.size == img.size == (1280, 720) and ov.mode == "RGBA"
        thumb = Image.open(BytesIO(fetch_media(client, f["thumbUrl"], THUMB_CACHE)))
        assert thumb.size == (320, 180)
    assert frames[1]["heatmap"]["status"] == "not_requested"
    # Frames 0 and 2-3 are one stretch (a 1-frame gap does not split it).
    assert [(s["start"], s["end"]) for s in g["stretches"]] == [(0, 3)]
    (alert,) = client.get("/alerts", params={"game_id": game["id"]}).json()
    assert alert["status"] == "open" and alert["thumbUrl"].endswith("/thumb")
    assert alert["createdAt"].endswith("Z")
    j = client.get(f"/jobs/{job['id']}").json()
    assert j["status"] == "done" and j["modelId"] == "dummy@0.1" and j["framesPerSec"] > 0
    assert j["p95LatencyMs"] >= j["p50LatencyMs"] and j["localizeMsTotal"] > 0


def test_image_analysis(client, worker):
    r = analyze(client, jpeg(blurry=True), name="cam.jpg", ctype="image/jpeg")
    assert r.status_code == 202
    game = r.json()["game"]
    assert game["mediaKind"] == "image" and r.json()["job"]["totalFrames"] == 1
    run_all(worker)
    (f,) = client.get(f"/games/{game['id']}/frames").json()
    assert f["qualityIssue"] and f["heatmap"]["status"] == "available"


def test_global_defect_has_no_overlay(client, worker):
    r = analyze(client, jpeg(dark=True), name="night.jpg", ctype="image/jpeg")
    run_all(worker)
    (f,) = client.get(f"/games/{r.json()['game']['id']}/frames").json()
    assert any(d["type"] == "Low light" for d in f["detections"])
    assert f["heatmap"]["status"] in ("available", "unsupported")  # blur may co-occur


@pytest.mark.parametrize("settings_overrides", [{"localize_all_max_frames": 1}])
def test_long_video_localizes_alert_frames_only(client, worker, tmp_path):
    r = analyze(client, mp4(tmp_path / "m.mp4", seconds=30))  # 6 frames > 1: "long"
    run_all(worker)
    gid = r.json()["game"]["id"]
    frames = client.get(f"/games/{gid}/frames").json()
    (alert,) = client.get("/alerts", params={"game_id": gid}).json()
    hm = {f["index"]: f["heatmap"]["status"] for f in frames if f["qualityIssue"]}
    assert hm.pop(alert["frameIndex"]) == "available"  # the alerted frame has its heat map
    assert set(hm.values()) == {"not_requested"}  # other flagged frames do not


@pytest.mark.parametrize("settings_overrides", [{"generate": "all"}])
def test_generate_all(client, worker, tmp_path):
    r = analyze(client, mp4(tmp_path / "m.mp4", seconds=10, blur_from=1.0))  # all sharp
    run_all(worker)
    frames = client.get(f"/games/{r.json()['game']['id']}/frames").json()
    assert not any(f["qualityIssue"] for f in frames)
    assert all(f["latencyMs"] is not None for f in frames)


def test_upload_validation(client):
    r = analyze(client, b"GIF89a", name="a.gif", ctype="image/gif")
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_type"
    r = analyze(client, b"not an image", name="a.jpg", ctype="image/jpeg")
    assert r.status_code == 422
    assert r.json()["error"]["code"] in ("unsupported_format", "decode_failed")
    r = client.post(
        "/analyses", data={"home": "A"}, files={"file": ("a.jpg", jpeg(), "image/jpeg")}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"  # away, sport
    # Nothing reached the store, and no game was created.
    store = client.app_state.store
    if store.name == "s3":
        assert store.s3.list_objects_v2(Bucket=store.bucket).get("KeyCount", 0) == 0
    else:
        assert not any(p.is_file() for p in store.root.rglob("*"))
    assert client.get("/games").json() == []


@pytest.mark.parametrize("settings_overrides", [{"max_video_sec": 10}])
def test_too_long(client, tmp_path):
    r = analyze(client, mp4(tmp_path / "m.mp4", seconds=15))
    assert r.status_code == 422 and r.json()["error"]["code"] == "too_long"
    assert client.get("/games").json() == []


@pytest.mark.parametrize("settings_overrides", [{"max_upload_mb": 0}])
def test_too_large(client):
    r = analyze(client, jpeg(), name="a.jpg", ctype="image/jpeg")
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"


def test_default_limits():
    s = make_settings("/x")
    assert s.max_upload_mb == 20480 and s.max_video_sec == 36000  # 20 GB, 10 hours


# ---- games, re-runs, deletion ------------------------------------------------------------


def test_game_crud_and_search(client):
    body = {"home": "A", "away": "B", "sport": "Soccer", "date": "2026-11-15", "camera": "Spiideo"}
    r = client.post("/games", json=body)
    assert r.status_code == 201 and r.json()["status"] == "no-video"
    gid = r.json()["id"]
    assert client.post("/jobs/match", json={"gameId": gid}).json()["error"]["code"] == "no_video"
    assert client.patch(f"/games/{gid}", json={"venue": "Field 2"}).json()["venue"] == "Field 2"
    assert [g["id"] for g in client.get("/games", params={"q": "field 2"}).json()] == [gid]
    assert [g["id"] for g in client.get("/games", params={"q": "spiideo"}).json()] == [gid]
    assert client.delete(f"/games/{gid}").status_code == 204
    r = client.get(f"/games/{gid}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "game_not_found"
    assert r.headers["X-Request-ID"]


def test_rerun_replaces_frames_and_keeps_alerts(client, worker, tmp_path):
    gid = analyze(client, mp4(tmp_path / "m.mp4", seconds=20)).json()["game"]["id"]
    run_all(worker)
    alerts = client.get("/alerts", params={"game_id": gid}).json()
    j1 = client.post("/jobs/match", json={"gameId": gid})
    assert j1.status_code == 202
    assert client.post("/jobs/match", json={"gameId": gid}).json()["id"] == j1.json()["id"]
    run_all(worker)
    assert client.get(f"/games/{gid}").json()["analyzedFrames"] == 4
    assert len(client.get("/alerts", params={"game_id": gid}).json()) == len(alerts)


def test_media_keys_and_delete(client, worker, tmp_path):
    store = client.app_state.store
    r = analyze(client, mp4(tmp_path / "m.mp4", seconds=12))
    gid, jid = r.json()["game"]["id"], r.json()["job"]["id"]
    run_all(worker)
    with dbm.session() as db:
        game = db.get(Game, gid)
        frames = db.scalars(select(Frame).where(Frame.game_id == gid)).all()
        keys = [game.video_key, game.poster_key]
        keys += [k for f in frames for k in (f.image_key, f.thumb_key)]
    assert keys[0].startswith(f"games/{gid}/video/") and keys[1] == f"games/{gid}/poster.jpg"
    assert all(k.startswith(f"games/{gid}/runs/{jid}/") for k in keys[2:])
    assert all(store.exists(k) for k in keys)
    assert client.delete(f"/games/{gid}").status_code == 204
    assert not any(store.exists(k) for k in keys)
    assert client.get(f"/media/games/{gid}/poster").status_code == 404


# ---- review, thresholds, feedback --------------------------------------------------------


def _alert(client, worker, tmp_path) -> dict:
    gid = analyze(client, mp4(tmp_path / "m.mp4", seconds=20)).json()["game"]["id"]
    run_all(worker)
    return client.get("/alerts", params={"game_id": gid}).json()[0]


def test_review_is_versioned_and_final(client, worker, tmp_path):
    a = _alert(client, worker, tmp_path)
    body = {"decision": "confirmed", "expectedVersion": a["version"]}
    r = client.post(f"/alerts/{a['id']}/review", json=body, headers={"X-StreamSense-User": "rev1"})
    assert r.status_code == 200
    out = r.json()
    # The reviewer comes from the session (auth off here: the built-in dev admin), never a header.
    assert out["decision"] == "confirmed" and out["reviewedBy"] == "dev"
    assert out["reviewedAt"].endswith("Z") and out["modelOutput"] == a["modelOutput"]
    body = {"decision": "dismissed", "expectedVersion": a["version"]}
    r = client.post(f"/alerts/{a['id']}/review", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_reviewed"


def test_threshold_versions_are_immutable(client, worker, tmp_path):
    a = _alert(client, worker, tmp_path)
    cur = client.get("/thresholds/current").json()
    new = client.post("/thresholds", json={"alertThreshold": 4}).json()
    assert new["id"] == cur["id"] + 1 and new["alertThreshold"] == 4
    assert [t["id"] for t in client.get("/thresholds").json()] == [new["id"], cur["id"]]
    assert client.get(f"/alerts/{a['id']}").json()["thresholdId"] == cur["id"]
    job = client.post("/jobs/match", json={"gameId": a["gameId"]}).json()
    assert job["thresholdId"] == new["id"]


def test_feedback_flow(client, worker, tmp_path):
    gid = _alert(client, worker, tmp_path)["gameId"]
    missed = {"gameId": gid, "frameIndex": 1, "kind": "missed", "defect": "Stitching",
              "severity": 2, "region": {"x": 0.4, "y": 0.6}}  # fmt: skip
    r = client.post("/feedback", json=missed)
    assert r.status_code == 201
    bad = {"gameId": gid, "frameIndex": 1, "kind": "missed"}
    assert client.post("/feedback", json=bad).status_code == 422
    client.post("/feedback", json={"gameId": gid, "frameIndex": 2, "kind": "correct"})
    s = client.get("/feedback/summary").json()
    assert (s["total"], s["missed"], s["observedPrecision"], s["canQueueFinetune"]) == (
        2,
        1,
        1.0,
        False,
    )
    assert "Stitching" in client.get("/feedback/export.csv").text
    assert client.post("/feedback/fine-tune").status_code == 409
    assert client.delete(f"/feedback/{r.json()['id']}").status_code == 204


# ---- worker durability -------------------------------------------------------------------


def test_expired_lease_requeues_and_resumes(client, worker, tmp_path):
    r = analyze(client, mp4(tmp_path / "m.mp4", seconds=60))  # 12 frames
    gid, jid = r.json()["game"]["id"], r.json()["job"]["id"]
    s4 = worker.s.model_copy(update={"batch_size": 4})
    dead = Worker(s4, DummyBackend(), worker.store, "dead")
    assert dead.claim() == jid
    from app.services import current_threshold, ensure_model_version

    with dbm.session() as db:
        t = current_threshold(db, worker.s)
        ensure_model_version(db, dead.backend)
        key = db.get(Game, gid).video_key
    with worker.store.local_copy(key) as path:  # a worker that wrote 2 batches and died
        batches = dead._media_batches(path, 5, 0, t)
        for _ in range(2):
            dead._save_batch(next(batches), jid, gid, "dummy@0.1", t, True)
    assert client.get(f"/jobs/{jid}").json()["doneFrames"] == 8
    with dbm.session() as db:
        db.execute(update(Job).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    assert worker.run_once()  # re-queues, claims, resumes from frame 8
    j = client.get(f"/jobs/{jid}").json()
    assert j["status"] == "done" and j["doneFrames"] == 12 and j["attempts"] == 2
    idx = [f["index"] for f in client.get(f"/games/{gid}/frames").json()]
    assert idx == list(range(12))  # no gaps, no duplicates


class Exploding(DummyBackend):
    def score(self, images):
        raise RuntimeError("CUDA error: device-side assert")


def test_failing_job_retries_then_fails_safely(client, worker):
    jid = analyze(client, jpeg(), name="a.jpg", ctype="image/jpeg").json()["job"]["id"]
    w = Worker(worker.s, Exploding(), worker.store, "w")
    for _ in range(worker.s.max_attempts):
        assert w.run_once()
    j = client.get(f"/jobs/{jid}").json()
    assert j["status"] == "failed" and j["failureCode"] == "internal_error"
    assert "CUDA" not in (j["error"] or "")  # internals never reach the client
    assert not w.run_once()


def test_cancel(client, worker):
    jid = analyze(client, jpeg(), name="a.jpg", ctype="image/jpeg").json()["job"]["id"]
    assert client.post(f"/jobs/{jid}/cancel").json()["status"] == "cancelled"
    assert not worker.run_once()


# ---- runs, bench, ops --------------------------------------------------------------------


def test_import_run(client, tmp_path):
    run = tmp_path / "run"
    (run / "eval_val").mkdir(parents=True)
    (run / "run_record.json").write_text(json.dumps({"experiment_id": "E-07c"}))
    blur = {"precision": 0.8, "recall": 0.5, "support": 51}
    metrics = {
        "split": "val",
        "binary_at_model_decision": {"precision": 0.9, "recall": 0.7, "f1": 0.79},
        "ranking": {"average_precision": 0.93},
        "calibration": {"bins": [{"confidence": 0.1, "observed": 0.05}]},
        "crew_classes": {"per_label": {"blur_lens_smear": blur,
                                       "weather": {"support": 0, "metrics": "omitted"}}},
        "operating_points": [{"fit": {"target_precision": 0.9, "precision": 0.91, "recall": 0.78}}],
    }  # fmt: skip
    (run / "eval_val" / "metrics.json").write_text(json.dumps(metrics))
    assert client.get("/runs").json() == []  # no placeholder runs
    r = client.post("/runs/import", json={"runDir": str(run), "published": True}).json()
    assert r["ap"] == 0.93 and r["perDefect"]["Blur"]["p"] == 0.8
    assert r["perDefect"]["Weather"]["p"] is None and r["tradeoff"]["p0.90"]["recall"] == 0.78
    assert client.get("/bench").json() == []


def test_starts_empty(client):
    assert client.get("/games").json() == [] and client.get("/alerts").json() == []


def test_health_reports_media_location(client):
    m = client.get("/health").json()["media"]
    assert m["backend"] == client.app_state.store.name
    assert m["location"].startswith("s3://ss-test/streamsense/") or m["location"].endswith("/media")


def test_refuses_ephemeral_media_dir():
    from app.config import Settings

    with pytest.raises(ValueError, match="not persistent"):
        Settings(_env_file=None, data_dir="/tmp/ss-media-check").check_persistent()
    Settings(
        _env_file=None, data_dir="/tmp/x", media_backend="s3", s3_bucket="b"
    ).check_persistent()
    Settings(_env_file=None, data_dir="/tmp/x", allow_ephemeral_media=True).check_persistent()


def test_token_gate(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(make_settings(tmp_path, token="s3cret"))) as c:
        assert c.get("/health").status_code == 200
        r = c.get("/games")
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
        assert c.get("/games", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert c.get("/games", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_token_from_env(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("STREAMSENSE_API_TOKEN", "abc")
    assert Settings(_env_file=None).token == "abc"


def test_import_evaluation_run(client, tmp_path):
    """A locked-test evaluation dir keeps metrics.json at the top level."""
    run = tmp_path / "eval"
    run.mkdir()
    (run / "run_record.json").write_text(json.dumps({"experiment_id": "E-07c"}))
    metrics = {"split": "test", "binary_at_model_decision": {"precision": 0.8, "recall": 0.69},
               "ranking": {"average_precision": 0.887}}  # fmt: skip
    (run / "metrics.json").write_text(json.dumps(metrics))
    r = client.post("/runs/import", json={"runDir": str(run)}).json()
    assert r["split"] == "test split" and r["ap"] == 0.887
    assert client.delete(f"/runs/{r['id']}").status_code == 204
    assert client.get("/runs").json() == []


# ---- direct browser -> S3 uploads ---------------------------------------------------------


def _direct_upload(client, data: bytes, ctype="video/mp4", name="m.mp4", corrupt_size=False):
    """What the browser does: start, PUT each part (here via the S3 client: the test transport
    cannot reach presigned URLs), then complete with the ETags and the game metadata."""
    from app.models import Upload

    r = client.post("/uploads", json={"filename": name, "contentType": ctype, "size": len(data)})
    assert r.status_code == 201, r.json()
    up = r.json()
    assert (
        up["parts"][0]["url"].startswith("https://") and "X-Amz-Signature" in up["parts"][0]["url"]
    )
    store = client.app_state.store
    with dbm.session() as db:
        row = db.get(Upload, up["uploadId"])
        key, s3_id = store._k(row.key), row.s3_upload_id
    size = up["partSize"]
    parts = []
    for p in up["parts"]:
        n = p["partNumber"]
        chunk = data[(n - 1) * size : n * size]
        if corrupt_size and n == len(up["parts"]):
            chunk = chunk[:-1]
        e = store.s3.upload_part(
            Bucket=store.bucket, Key=key, UploadId=s3_id, PartNumber=n, Body=chunk
        )
        parts.append({"partNumber": n, "etag": e["ETag"]})
    meta = {"home": "Westview", "away": "Lakeside", "sport": "Soccer", "camera": "Pixellot"}
    return client.post(f"/uploads/{up['uploadId']}/complete", json={"parts": parts, **meta})


def test_direct_upload_unavailable_on_local_store(client):
    if client.app_state.store.name == "s3":
        pytest.skip("local-store behaviour")
    r = client.post("/uploads", json={"filename": "a.mp4", "contentType": "video/mp4", "size": 10})
    assert r.status_code == 409 and r.json()["error"]["code"] == "direct_upload_unavailable"
    assert client.get("/model").json()["directUpload"] is False


@pytest.mark.parametrize("settings_overrides", [{"multipart_part_mb": 5}])
def test_direct_upload_end_to_end(client, worker, tmp_path):
    if client.app_state.store.name != "s3":
        pytest.skip("needs the S3 store")
    assert client.get("/model").json()["directUpload"] is True
    data = mp4(tmp_path / "m.mp4", seconds=20, size=(1280, 720)).read_bytes()
    big = data + b"\0" * (11 << 20)  # >2 parts at 5 MB; MP4 decoders ignore trailing bytes
    r = _direct_upload(client, big)
    assert r.status_code == 202, r.json()
    game, job = r.json()["game"], r.json()["job"]
    assert game["status"] == "queued" and job["totalFrames"] == 0 and game["posterUrl"] is None
    run_all(worker)  # the worker decode-checks, makes the poster and sets the frame count
    g = client.get(f"/games/{game['id']}").json()
    assert g["status"] == "analyzed" and g["analyzedFrames"] == 4 and g["posterUrl"]
    j = client.get(f"/jobs/{job['id']}").json()
    assert j["status"] == "done" and j["totalFrames"] == 4
    assert (
        client.post(f"/uploads/{r.json()['job']['id']}/complete", json={"parts": []}).status_code
        == 422
    )


def test_direct_upload_size_mismatch_and_abort(client, tmp_path):
    if client.app_state.store.name != "s3":
        pytest.skip("needs the S3 store")
    data = mp4(tmp_path / "m.mp4", seconds=10).read_bytes()
    r = _direct_upload(client, data, corrupt_size=True)
    assert r.status_code == 422 and r.json()["error"]["code"] == "size_mismatch"
    assert client.get("/games").json() == []
    up = client.post(
        "/uploads", json={"filename": "a.mp4", "contentType": "video/mp4", "size": 100}
    ).json()
    assert client.post(f"/uploads/{up['uploadId']}/abort").status_code == 204
    assert client.post(f"/uploads/{up['uploadId']}/abort").status_code == 404
    r = client.post("/uploads", json={"filename": "a.gif", "contentType": "image/gif", "size": 1})
    assert r.status_code == 415


@pytest.mark.parametrize("settings_overrides", [{"max_video_sec": 10}])
def test_direct_upload_too_long_fails_in_worker(client, worker, tmp_path):
    if client.app_state.store.name != "s3":
        pytest.skip("needs the S3 store")
    r = _direct_upload(client, mp4(tmp_path / "m.mp4", seconds=15).read_bytes())
    assert r.status_code == 202
    run_all(worker)
    j = client.get(f"/jobs/{r.json()['job']['id']}").json()
    assert j["status"] == "failed" and j["failureCode"] == "too_long"


# ---- job stages (what the UI shows while frames are still 0) -----------------------------


def test_queued_jobs_report_position(client, tmp_path):
    a = analyze(client, jpeg(), name="a.jpg", ctype="image/jpeg").json()["job"]
    b = analyze(client, jpeg(), name="b.jpg", ctype="image/jpeg").json()["job"]
    assert (a["stage"], a["queuePosition"]) == ("queued", 1)
    assert client.get(f"/jobs/{b['id']}").json()["queuePosition"] == 2


def test_worker_reports_stages(client, worker, tmp_path, monkeypatch):
    seen: list[tuple] = []
    orig = Worker._stage

    def spy(self, job_id, stage, detail, progress, force=False):
        seen.append((stage, detail, progress))
        orig(self, job_id, stage, detail, progress, force)

    monkeypatch.setattr(Worker, "_stage", spy)
    if client.app_state.store.name == "s3":
        r = _direct_upload(client, mp4(tmp_path / "m.mp4", seconds=20).read_bytes())
    else:
        r = analyze(client, mp4(tmp_path / "m.mp4", seconds=20))
    jid = r.json()["job"]["id"]
    run_all(worker)
    stages = [s for s, _, _ in seen]
    if client.app_state.store.name == "s3":
        assert stages[0] == "downloading" and seen[-2][2] is not None  # MB progress reported
        assert any("MB" in (d or "") for _, d, _ in seen)
    assert stages[-1] == "finishing"
    j = client.get(f"/jobs/{jid}").json()
    assert j["status"] == "done" and j["stage"] is None and j["heartbeatAt"].endswith("Z")


def test_eta_while_analyzing(client):
    from app.routers.common import _eta

    j = Job(id="x", label="x", kind="match", status="running", stage="analyzing",
            total_frames=100, done_frames=30, stage_start_frames=10,
            stage_started_at=datetime.now(UTC) - timedelta(seconds=40))  # fmt: skip
    assert _eta(j) == pytest.approx(140, abs=2)  # 20 frames / 40 s -> 70 left -> 140 s


def test_add_missing_columns(tmp_path):
    import sqlite3

    from app.db import init_engine

    db = tmp_path / "old.db"
    init_engine(f"sqlite:///{db}")  # today's schema ...
    con = sqlite3.connect(db)
    new = ["stage", "stage_detail", "stage_progress", "heartbeat_at", "stage_started_at",
           "stage_start_frames"]  # fmt: skip
    for c in new:  # ... minus the stage columns = a database from before they existed
        con.execute(f"ALTER TABLE jobs DROP COLUMN {c}")
    con.execute("INSERT INTO jobs (id, label, kind, status, sample_interval_ms, total_frames, "
                "done_frames, flagged_frames, hardware, mean_latency_ms, max_latency_ms, "
                "localize_ms_total, attempts, created_at) VALUES ('j1', 'old row', 'match', "
                "'done', 5000, 1, 1, 0, '', 0, 0, 0, 1, '2026-11-15')")  # fmt: skip
    con.commit()
    con.close()
    init_engine(f"sqlite:///{db}")
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(jobs)")}
    assert set(new) <= cols
    assert sqlite3.connect(db).execute("SELECT label FROM jobs").fetchone() == ("old row",)


def test_add_missing_columns_refuses_required_columns(tmp_path):
    import sqlite3

    from app.db import init_engine

    db = tmp_path / "older.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE jobs (id VARCHAR(64) PRIMARY KEY, label VARCHAR NOT NULL)")
    con.commit()
    con.close()
    with pytest.raises(RuntimeError, match="needs a migration"):
        init_engine(f"sqlite:///{db}")


# ---- status page -------------------------------------------------------------------------


def test_status_aggregates_and_live_workers(client, worker, tmp_path):
    s = client.get("/status").json()
    assert s["summary"]["jobsDone"] == 0 and len(s["series"]) == 24 and s["live"]["gpus"] == []
    analyze(client, mp4(tmp_path / "a.mp4", seconds=60))  # 12 frames = 60 s of video
    analyze(client, jpeg(), name="b.jpg", ctype="image/jpeg")
    assert client.get("/status").json()["live"]["queued"] == 2
    run_all(worker)
    worker._beat("idle", force=True)
    s = client.get("/status").json()
    sm = s["summary"]
    assert sm["jobsDone"] == 2 and sm["successRate"] == 1.0 and sm["frames"] == 13
    assert sm["videoHours"] == pytest.approx(60 / 3600, abs=1e-4)
    assert sm["speedX"] > 0 and sm["fps"] > 0 and sm["queueWaitP50Sec"] is not None
    (g,) = s["byGpu"]
    assert g["hardware"] == "test-cpu" and g["jobs"] == 2 and 0 <= g["busyPct"] <= 100
    assert sum(p["jobs"] for p in s["series"]) == 2 and s["series"][-1]["jobs"] == 2
    (w,) = s["live"]["gpus"]
    assert w["hardware"] == "test-cpu" and w["state"] == "idle"
    s7 = client.get("/status", params={"range": "7d"}).json()
    assert s7["bucketSec"] == 6 * 3600 and len(s7["series"]) == 28
    assert client.get("/status", params={"range": "1y"}).status_code == 422


def test_status_counts_failures(client, worker):
    analyze(client, jpeg(), name="a.jpg", ctype="image/jpeg")
    w = Worker(worker.s, Exploding(), worker.store, "w")
    for _ in range(worker.s.max_attempts):
        w.run_once()
    sm = client.get("/status").json()["summary"]
    assert sm["jobsFailed"] == 1 and sm["successRate"] == 0.0


# ---- cloud GPU on demand -----------------------------------------------------------------


def test_model_info_reports_the_online_worker(client, worker):
    assert client.get("/model").json()["backend"] == "dummy"  # no worker online yet
    worker._beat("idle", force=True)
    m = client.get("/model").json()
    assert m["backend"] == "worker" and m["hardware"] == "test-cpu" and m["modelId"] == "dummy@0.1"


def test_wake_gpu_only_when_no_worker_online(client, worker, monkeypatch):
    import sys
    import types

    from app.services import wake_gpu

    calls = []

    class FakeEC2:
        def describe_instances(self, InstanceIds):
            return {"Reservations": [{"Instances": [{"State": {"Name": "stopped"}}]}]}

        def start_instances(self, InstanceIds):
            calls.append(InstanceIds)

    monkeypatch.setitem(
        sys.modules, "boto3", types.SimpleNamespace(client=lambda *a, **k: FakeEC2())
    )
    s = worker.s.model_copy(update={"gpu_instance_id": "i-123"})
    with dbm.session() as db:
        assert wake_gpu(db, s) is True and calls == [["i-123"]]
    worker._beat("idle", force=True)
    with dbm.session() as db:
        assert wake_gpu(db, s) is False and len(calls) == 1  # a worker is online
        assert wake_gpu(db, worker.s) is False  # not configured


def test_idle_worker_stops_its_machine(client, worker, tmp_path):
    import threading

    marker = tmp_path / "stopped"
    s = worker.s.model_copy(update={"idle_shutdown_sec": 0, "idle_shutdown_cmd": f"touch {marker}"})
    w = Worker(s, DummyBackend(), worker.store, "idle-w")
    t = threading.Thread(target=w.run_forever, daemon=True)
    t.start()
    t.join(timeout=10)
    assert marker.exists() and not t.is_alive()
    from app.models import WorkerState

    with dbm.session() as db:
        assert db.get(WorkerState, "idle-w").state == "stopped"


def test_large_upload_sizes_fit_postgres():
    """Postgres INTEGER is 32-bit: byte counts of 10 GB uploads need BIGINT."""
    from sqlalchemy import BigInteger

    from app.models import Upload

    assert isinstance(Upload.__table__.c.size.type, BigInteger)


def test_worker_module_entrypoint_runs_after_helpers():
    """`python -m app.worker` executes top to bottom: main() must come after every helper."""
    src = (Path(__file__).resolve().parents[1] / "app" / "worker.py").read_text()
    assert src.rstrip().endswith('if __name__ == "__main__":\n    main()')


def test_alerts_need_consecutive_flagged_frames(client):
    """One flagged sample never alerts a video; two in a row do (also across batches)."""
    from app.services import current_threshold, longest_run, raise_alerts, recompute_alerts

    assert [longest_run(x) for x in ([], [3], [1, 3, 5], [1, 2, 4, 5, 6])] == [0, 1, 1, 3]
    body = {"home": "A", "away": "B", "sport": "Soccer", "date": "2026-11-15"}
    gid = client.post("/games", json=body).json()["id"]
    bad = [{"type": "Blur", "severity": 4}]

    def frame(i, flagged):
        return Frame(game_id=gid, job_id=None, index=i, timestamp_ms=i * 5000, issue_score=0.9 if flagged else 0.1,
                     quality_issue=flagged, defects=bad if flagged else [])  # fmt: skip

    with dbm.session() as db:
        game, th = db.get(Game, gid), current_threshold(db, client.app_state.settings)
        db.add_all(
            [frame(0, True), frame(1, False), frame(2, False), frame(3, False), frame(4, True)]
        )
        db.commit()
        assert raise_alerts(db, game, th, since_index=0, min_frames=2) == []  # two lone hits
        db.add(frame(5, True))  # the next batch makes frame 4's run persistent
        db.commit()
        (a,) = raise_alerts(db, game, th, since_index=5, min_frames=2)
        assert a.id == f"alr-{gid}-4"
        # An old single-frame alert (raised under min_frames=1) is removed when recomputed.
        raise_alerts(db, game, th, since_index=0, min_frames=1)
        assert {x.id for x in db.scalars(select(Alert).where(Alert.game_id == gid))} == {
            f"alr-{gid}-0", f"alr-{gid}-4"}  # fmt: skip
        assert recompute_alerts(db, game, th, min_frames=2) == (0, 1)
        assert [x.id for x in db.scalars(select(Alert).where(Alert.game_id == gid))] == [
            f"alr-{gid}-4"
        ]


def test_busy_worker_stays_online_during_a_long_job(client, worker, tmp_path):
    """A worker that last beat long ago is still online while its running job makes progress."""
    from app.models import WorkerState

    analyze(client, mp4(tmp_path / "a.mp4", seconds=10))
    jid = worker.claim()
    worker._beat("busy", jid, force=True)
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
    with dbm.session() as db:
        db.get(WorkerState, worker.id).last_seen_at = old
        job = db.get(Job, jid)
        job.heartbeat_at = old
        db.commit()
    assert client.get("/status").json()["live"]["gpus"] == []  # silent: offline
    with dbm.session() as db:
        db.get(Job, jid).heartbeat_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
    (g,) = client.get("/status").json()["live"]["gpus"]
    assert g["state"] == "busy" and g["jobId"] == jid


# ---- scheduling: shortest remaining work first, preemption, aging --------------------------

SCHED = {"batch_size": 2, "sched_check_sec": 0, "preempt_min_frames": 0}


@pytest.mark.parametrize("settings_overrides", [SCHED])
def test_queue_runs_shortest_job_first(client, worker, tmp_path):
    long = analyze(client, mp4(tmp_path / "l.mp4", seconds=60)).json()["job"]["id"]
    short = analyze(client, mp4(tmp_path / "s.mp4", seconds=10)).json()["job"]["id"]
    assert client.get(f"/jobs/{short}").json()["queuePosition"] == 1
    assert client.get(f"/jobs/{long}").json()["queuePosition"] == 2
    assert worker.claim() == short


@pytest.mark.parametrize("settings_overrides", [SCHED])
def test_aging_lets_a_long_wait_win(client, worker, tmp_path):
    long = analyze(client, mp4(tmp_path / "l.mp4", seconds=60)).json()["job"]["id"]
    analyze(client, mp4(tmp_path / "s.mp4", seconds=10))
    with dbm.session() as db:  # waited 10 s: 80 video-seconds of credit beats 50 s more work
        db.get(Job, long).queued_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=10)
        db.commit()
    assert worker.claim() == long


@pytest.mark.parametrize("settings_overrides", [{**SCHED, "sched_policy": "fifo"}])
def test_fifo_policy(client, worker, tmp_path):
    long = analyze(client, mp4(tmp_path / "l.mp4", seconds=60)).json()["job"]["id"]
    analyze(client, mp4(tmp_path / "s.mp4", seconds=10))
    assert worker.claim() == long


@pytest.mark.parametrize("settings_overrides", [SCHED])
def test_long_job_pauses_for_a_short_one_and_resumes(client, worker, tmp_path):
    r = analyze(client, mp4(tmp_path / "l.mp4", seconds=60))  # 12 frames
    long, gid = r.json()["job"]["id"], r.json()["game"]["id"]
    assert worker.claim() == long
    short = analyze(client, mp4(tmp_path / "s.mp4", seconds=10)).json()["job"]["id"]
    worker.process(long)  # yields after its first batch
    j = client.get(f"/jobs/{long}").json()
    assert j["status"] == "queued" and j["stage"] == "paused" and 0 < j["doneFrames"] < 12
    with dbm.session() as db:
        job = db.get(Job, long)
        assert job.preemptions == 1 and job.attempts == 0  # a pause is not a failed attempt
    assert worker.claim() == short
    worker.process(short)
    assert client.get(f"/jobs/{short}").json()["status"] == "done"
    run_all(worker)  # resumes the long job where it stopped
    j = client.get(f"/jobs/{long}").json()
    assert j["status"] == "done" and j["doneFrames"] == 12
    idx = [f["index"] for f in client.get(f"/games/{gid}/frames").json()]
    assert idx == list(range(12))  # nothing lost or analyzed twice


@pytest.mark.parametrize("settings_overrides", [SCHED])
def test_no_pause_while_another_gpu_is_idle(client, worker, tmp_path):
    from app.models import WorkerState

    long = analyze(client, mp4(tmp_path / "l.mp4", seconds=60)).json()["job"]["id"]
    assert worker.claim() == long
    analyze(client, mp4(tmp_path / "s.mp4", seconds=10))
    with dbm.session() as db:
        db.add(WorkerState(id="other-gpu", hardware="x", state="idle", started_at=datetime.now(UTC).replace(tzinfo=None),
                           last_seen_at=datetime.now(UTC).replace(tzinfo=None)))  # fmt: skip
        db.commit()
    worker.process(long)
    assert client.get(f"/jobs/{long}").json()["status"] == "done"  # the idle GPU takes the clip


@pytest.mark.parametrize("settings_overrides", [SCHED])
def test_equal_jobs_never_both_yield(client, tmp_path):
    """Two GPUs on equally long jobs: exactly one pauses for the short clip."""
    from app.scheduler import should_yield

    a = analyze(client, mp4(tmp_path / "a.mp4", seconds=60)).json()["job"]["id"]
    b = analyze(client, mp4(tmp_path / "b.mp4", seconds=60)).json()["job"]["id"]
    analyze(client, mp4(tmp_path / "s.mp4", seconds=10))
    s = client.app_state.settings
    with dbm.session() as db:
        for jid, w in ((a, "gpu-a"), (b, "gpu-b")):
            j = db.get(Job, jid)
            j.status, j.worker_id = "running", w
        db.commit()
        yields = [
            should_yield(db, db.get(Job, jid), w, s) is not None
            for jid, w in ((a, "gpu-a"), (b, "gpu-b"))
        ]
    assert sorted(yields) == [False, True]


# ---- batching ------------------------------------------------------------------------------


def test_batch_size_auto_and_explicit():
    from app.inference import auto_batch_size

    assert auto_batch_size(12) == 12  # an explicit setting wins
    assert auto_batch_size(0) in (8, 16, 32)  # sized to the GPU (8 on CPU)


def test_out_of_memory_halves_the_batch(worker, monkeypatch):
    calls = []

    def fake(ims):
        calls.append(len(ims))
        if len(ims) > 2:
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        return [x * 10 for x in ims]

    import sys
    import types

    torch = types.SimpleNamespace(cuda=types.SimpleNamespace(empty_cache=lambda: None))
    monkeypatch.setitem(sys.modules, "torch", torch)  # stand-in for empty_cache (CPU tests)
    assert worker._oom_safe(fake, [1, 2, 3, 4, 5, 6, 7, 8]) == [10, 20, 30, 40, 50, 60, 70, 80]
    assert worker.batch == 2 and calls[0] == 8  # smaller from now on; nothing lost or reordered
    with pytest.raises(ValueError):
        worker._oom_safe(lambda ims: (_ for _ in ()).throw(ValueError("other")), [1, 2])
