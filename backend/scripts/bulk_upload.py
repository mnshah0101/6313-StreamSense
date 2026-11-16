"""Upload local videos through the API's direct-to-S3 path (what the web app does) and queue
their analysis. Parts go straight to S3 in parallel; nothing passes through the API host.

  python scripts/bulk_upload.py --api https://HOST --email admin --password-file PW \
      [--home H --away A --sport S] VIDEO [VIDEO ...]

Without --home, the file name (minus extension) is used as the home name. Prints one JSON line
per upload with the game and job ids.
"""

import argparse
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from pathlib import Path


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            self.base + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", "X-Requested-With": "streamsense"},
        )  # fmt: skip
        try:
            with self.http.open(req, timeout=120) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            sys.exit(f"{method} {path}: {e.code} {e.read()[:300]!r}")


def put_part(url: str, f: Path, offset: int, size: int) -> str:
    with f.open("rb") as fh:
        fh.seek(offset)
        data = fh.read(size)
    for attempt in range(1, 6):
        try:
            req = urllib.request.Request(url, data=data, method="PUT")
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.headers["ETag"]
        except (urllib.error.URLError, TimeoutError):
            if attempt == 5:
                raise
            time.sleep(2 * attempt)
    raise RuntimeError("unreachable")


def upload(api: Api, f: Path, meta: dict, workers: int) -> dict:
    ctype = mimetypes.guess_type(f.name)[0] or "video/mp4"
    plan = api.call("POST", "/uploads", {"filename": f.name, "contentType": ctype, "size": f.stat().st_size})
    size, parts = plan["partSize"], plan["parts"]
    t0, done = time.time(), [0]

    def one(p: dict) -> dict:
        etag = put_part(p["url"], f, (p["partNumber"] - 1) * size, size)
        done[0] += 1
        if done[0] % 10 == 0 or done[0] == len(parts):
            mb = min(done[0] * size, f.stat().st_size) / 2**20
            print(f"  {f.name}: {done[0]}/{len(parts)} parts, {mb / max(time.time() - t0, 1e-6):.0f} MB/s", flush=True)
        return {"partNumber": p["partNumber"], "etag": etag}

    with ThreadPoolExecutor(workers) as pool:
        done_parts = list(pool.map(one, parts))
    return api.call("POST", f"/uploads/{plan['uploadId']}/complete", {"parts": done_parts, **meta})


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--password-file", required=True)
    p.add_argument("--home")
    p.add_argument("--away", default="PlayOn recording")
    p.add_argument("--sport", default="Unknown")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("files", nargs="+")
    a = p.parse_args()
    api = Api(a.api)
    api.call("POST", "/auth/login", {"email": a.email, "password": Path(a.password_file).read_text().strip()})
    for name in a.files:
        f = Path(name)
        meta = {"home": a.home or f.stem, "away": a.away, "sport": a.sport}
        r = upload(api, f, meta, a.workers)
        print(json.dumps({"file": f.name, "game": r["game"]["id"], "job": r["job"]["id"]}), flush=True)


if __name__ == "__main__":
    main()
