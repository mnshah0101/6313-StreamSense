import io
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageFilter

from app.config import Settings
from app.main import create_app
from app.worker import Worker


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """Tests never see the developer's .env, service settings or real AWS credentials."""
    import os

    for k in list(os.environ):
        if k.startswith(("STREAMSENSE_API_", "AWS_")):
            monkeypatch.delenv(k)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")  # moto only
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


def make_settings(tmp: Path, **kw) -> Settings:
    return Settings(
        _env_file=None,  # never the developer's .env
        data_dir=tmp,
        embedded_worker=False,
        hardware_label="test-cpu",
        allow_ephemeral_media=True,
        auth_mode=kw.pop("auth_mode", "off"),  # auth itself is tested in test_auth.py
        **kw,
    )


@pytest.fixture
def settings_overrides() -> dict:
    """Override in a test module/function to change service settings."""
    return {}


@pytest.fixture(params=["local", "s3"])
def client(request, tmp_path, settings_overrides):
    """Every API test runs against both media stores; S3 is mocked in-process by moto."""
    if request.param == "local":
        app = create_app(make_settings(tmp_path, **settings_overrides))
        with TestClient(app) as c:
            c.app_state = app.state
            yield c
        return
    import boto3
    from moto import mock_aws

    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="ss-test")
        s3 = dict(media_backend="s3", s3_bucket="ss-test", s3_region="us-east-1")
        app = create_app(make_settings(tmp_path, **s3, **settings_overrides))
        with TestClient(app) as c:
            c.app_state = app.state
            yield c


@pytest.fixture
def worker(client) -> Worker:
    st = client.app_state
    return Worker(st.settings, st.backend, st.store, worker_id="test-worker")


META = {"home": "Westview", "away": "Lakeside", "sport": "Soccer", "league": "Varsity Boys",
        "venue": "Westview Stadium", "camera": "Pixellot", "date": "2026-11-15",
        "start_time": "7:30 PM"}  # fmt: skip


def analyze(client, path_or_bytes, name="m.mp4", ctype="video/mp4", **meta):
    data = path_or_bytes.read_bytes() if isinstance(path_or_bytes, Path) else path_or_bytes
    return client.post("/analyses", data={**META, **meta}, files={"file": (name, data, ctype)})


def fetch_media(client, url: str, cache: str = "private, no-store") -> bytes:
    """GET a /media URL: local streams bytes; S3 redirects to a presigned URL (checked here,
    then read with the store's own client because the test transport only reaches the app)."""
    from urllib.parse import parse_qs, urlparse

    r = client.get(url, follow_redirects=False)
    if r.status_code == 200:
        assert r.headers["cache-control"] == cache
        return r.content
    assert r.status_code == 307, r.text
    loc = urlparse(r.headers["location"])
    q = parse_qs(loc.query)
    assert r.headers["cache-control"] == "private, no-store"  # the signed redirect itself
    assert "X-Amz-Signature" in q and q["response-cache-control"] == [cache]
    store = client.app_state.store
    key = loc.path.lstrip("/")
    if key.startswith(store.bucket + "/"):  # path-style URL
        key = key[len(store.bucket) + 1 :]
    return store.s3.get_object(Bucket=store.bucket, Key=key)["Body"].read()


def jpeg(blurry: bool = False, dark: bool = False, size=(640, 360)) -> bytes:
    rng = np.random.default_rng(0)
    a = (rng.random((size[1], size[0], 3)) * 255).astype(np.uint8)
    if dark:
        a = (a * 0.1).astype(np.uint8)
    im = Image.fromarray(a)
    if blurry:
        im = im.filter(ImageFilter.GaussianBlur(12))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


def mp4(path: Path, seconds: int = 12, fps: int = 5, size=(320, 180), black_sec: int = 0,
        blur_from: float = 0.5) -> Path:  # fmt: skip
    """Sharp noise, blurry from `blur_from` of the way through (a Blur stretch for the dummy)."""
    import cv2

    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    rng = np.random.default_rng(1)
    for i in range(seconds * fps):
        frame = (rng.random((size[1], size[0], 3)) * 255).astype(np.uint8)
        if i >= seconds * fps * blur_from:
            frame = cv2.GaussianBlur(frame, (31, 31), 0)
        if i < black_sec * fps:
            frame = np.zeros_like(frame)  # stream opening on black
        w.write(frame)
    w.release()
    return path
