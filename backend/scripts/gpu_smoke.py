"""End-to-end check of the real model backend on a GPU, through the HTTP API.

1. Uploads val frames one by one (image jobs) and checks the service reproduces the scores the
   training run saved for the same frames (scores/val.jsonl): proves the checkpoint, prompt
   and preprocessing are loaded exactly as trained.
2. Builds a "match" video from one val game's frames (each held 5 s), runs a match job, and
   prints the timeline, stretches, alerts and heat-map status.

usage: python scripts/gpu_smoke.py RUN_DIR PLAYONSPORTS_REPO [N_FRAMES]
"""

import json
import random
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.worker import Worker


def main() -> None:
    run_dir, repo = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    images = repo / "data" / "extracted" / "partition_1"
    saved = {
        r["key"]: r["quality_issue"]
        for r in map(json.loads, (run_dir / "scores" / "val.jsonl").read_text().splitlines())
    }
    keys = sorted(saved, key=saved.get)
    random.seed(0)
    pick = keys[: n // 2] + keys[-(n - n // 2) :]  # clearest negatives and positives

    tmp = Path(tempfile.mkdtemp(prefix="ss-gpu-smoke-"))
    s = Settings(
        data_dir=tmp, backend="streamsense", run_dir=run_dir, streamsense_repo=repo,
        embedded_worker=False, batch_size=8, allow_ephemeral_media=True,
    )  # fmt: skip
    app = create_app(s)
    with TestClient(app) as c:
        st = app.state
        w = Worker(st.settings, st.backend, st.store, "smoke")
        t0 = time.perf_counter()
        st.backend.load()
        print(f"model load {time.perf_counter() - t0:.1f}s  {c.get('/model').json()}")

        # 1. score parity on single images
        jobs = {}
        for k in pick:
            meta = {"home": "Val", "away": k, "sport": "Soccer"}
            r = c.post("/analyses", data=meta, files={"file": (k.replace("/", "_"),
                       (images / k).read_bytes(), "image/jpeg")})  # fmt: skip
            assert r.status_code == 202, r.json()
            jobs[k] = (r.json()["job"]["id"], r.json()["game"]["id"])
        t0 = time.perf_counter()
        while w.run_once():
            pass
        dt = time.perf_counter() - t0
        diffs = []
        print("\nkey                                   saved   service  defects / heatmap")
        for k, (jid, gid) in jobs.items():
            job = c.get(f"/jobs/{jid}").json()
            assert job["status"] == "done", job
            (f,) = c.get(f"/games/{gid}/frames").json()
            diffs.append(abs(f["score"] - saved[k]))
            dets = ",".join(f"{d['type']}:{d['severity']}" for d in f["detections"]) or "-"
            print(f"{k:36s} {saved[k]:.4f}  {f['score']:.4f}   {dets} / {f['heatmap']['status']}"
                  f"{' ' + f['heatmap']['method'] if f['heatmap']['method'] else ''}")  # fmt: skip
        print(f"\nmax |score diff| = {max(diffs):.4g} over {len(diffs)} frames "
              f"({'PASS' if max(diffs) < 1e-2 else 'FAIL'}; training reload check uses 1e-2)")  # fmt: skip
        print(f"{len(jobs)} image jobs in {dt:.1f}s incl. heat maps for flagged spatial frames")

        # 2. a match built from one val game's frames
        import cv2
        import numpy as np
        from PIL import Image

        game_id = max({k.split("/")[0] for k in saved},
                      key=lambda g: sum(k.startswith(g) for k in saved))  # fmt: skip
        frames = sorted(k for k in saved if k.startswith(game_id + "/"))
        vid = tmp / "match.mp4"
        wr = cv2.VideoWriter(str(vid), cv2.VideoWriter_fourcc(*"mp4v"), 2, (896, 504))
        for k in frames:
            a = np.asarray(Image.open(images / k).convert("RGB").resize((896, 504)))
            for _ in range(10):  # 2 fps x 5 s per frame
                wr.write(cv2.cvtColor(a, cv2.COLOR_RGB2BGR))
        wr.release()
        r = c.post("/analyses", data={"home": "Val", "away": game_id, "sport": "Soccer"},
                   files={"file": ("m.mp4", vid.read_bytes(), "video/mp4")})  # fmt: skip
        assert r.status_code == 202, r.json()
        gid, job = r.json()["game"]["id"], r.json()["job"]
        t0 = time.perf_counter()
        while w.run_once():
            pass
        job = c.get(f"/jobs/{job['id']}").json()
        print(f"\nmatch {game_id}: {len(frames)} val frames -> job {job['status']} "
              f"{job['doneFrames']}/{job['totalFrames']} in {time.perf_counter() - t0:.1f}s, "
              f"mean {job['meanLatencyMs']:.0f} ms/frame on {job['hardware']}")  # fmt: skip
        g = c.get(f"/games/{gid}").json()
        print(
            "stretches:", [(x["start"], x["end"], x["worst"], x["defects"]) for x in g["stretches"]]
        )
        print("alerts:", [(a["id"], a["detections"]) for a in c.get("/alerts").json()])
        tl = c.get(f"/games/{gid}/frames").json()
        print("timeline:", " ".join(f"{f['index']}:{f['score']:.2f}" for f in tl))
        hm = [f["heatmap"] for f in tl if f["qualityIssue"]]
        print("heatmaps:", [(h["status"], h["method"], h["heat"]) for h in hm][:6])
        ov = next((h["overlayUrl"] for h in hm if h["overlayUrl"]), None)
        if ov:
            r = c.get(ov)
            print("overlay", ov, r.status_code, r.headers["content-type"], len(r.content), "bytes")


if __name__ == "__main__":
    main()
