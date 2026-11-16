"""Private media store: uploads, sampled frames and heat-map overlays, addressed by key.

Two implementations behind one interface:
- LocalMediaStore: a directory (development, tests, single-host deployments).
- S3MediaStore: an S3 bucket (AWS S3, or MinIO / Cloudflare R2 via an endpoint URL).

Keys are generated server-side, never taken from a request. Uploads are received into a local
temp file and checked (size, decoded format) before they are stored, so nothing unvalidated
reaches the bucket. The API serves media only after its own record lookup: the local store
streams the file; the S3 store redirects to a short-lived presigned URL that carries
`Cache-Control: private, no-store`.
"""

import hashlib
import io
import shutil
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from fastapi.responses import FileResponse, RedirectResponse, Response
from PIL import Image

CHUNK = 1 << 20
NO_STORE = "private, no-store"  # full frames and overlays
THUMB_CACHE = "private, max-age=300"  # thumbnails: browser-only cache, never shared caches
POSTER_SIZE = (640, 360)
THUMB_SIZE = (320, 180)


def thumbnail(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Aspect-preserving downscale (never upscales)."""
    im = image.convert("RGB")
    im.thumbnail(size, Image.Resampling.LANCZOS)
    return im


class TooLarge(ValueError):
    pass


@contextmanager
def receive(src: BinaryIO, max_bytes: int, suffix: str = "") -> Iterator[tuple[Path, int, str]]:
    """Spool an upload to a local temp file, enforcing a size limit.
    Yields (path, bytes, sha256); the temp file is removed afterwards."""
    h, n = hashlib.sha256(), 0
    fd = tempfile.NamedTemporaryFile(prefix="ss-upload-", suffix=suffix, delete=False)
    path = Path(fd.name)
    try:
        with fd:
            while chunk := src.read(CHUNK):
                n += len(chunk)
                if n > max_bytes:
                    raise TooLarge("too_large")
                h.update(chunk)
                fd.write(chunk)
        yield path, n, h.hexdigest()
    finally:
        path.unlink(missing_ok=True)


def encode_image(image: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    image.save(buf, fmt, **({"quality": 90} if fmt == "JPEG" else {}))
    return buf.getvalue()


class MediaStore(ABC):
    name = "base"

    @abstractmethod
    def put_file(self, key: str, path: Path, content_type: str) -> None: ...

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str) -> None: ...

    @abstractmethod
    def exists(self, key: str | None) -> bool: ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None:
        """Delete one key, or every key under `prefix/`."""

    @abstractmethod
    @contextmanager
    def local_copy(self, key: str, on_progress=None) -> Iterator[Path]:  # noqa: ANN001
        """A local file with the object's bytes, for decoding (removed afterwards if temporary)."""

    @abstractmethod
    def serve(self, key: str, media_type: str, cache: str = NO_STORE) -> Response:
        """HTTP response for an authorised request (the caller has already checked access)."""

    def put_thumbnail(self, key: str, image: Image.Image, size=THUMB_SIZE) -> None:  # noqa: ANN001
        buf = io.BytesIO()
        thumbnail(image, size).save(buf, "JPEG", quality=80, optimize=True)
        self.put_bytes(key, buf.getvalue(), "image/jpeg")

    def put_image(self, key: str, image: Image.Image, fmt: str = "JPEG") -> None:
        self.put_bytes(
            key, encode_image(image, fmt), "image/jpeg" if fmt == "JPEG" else "image/png"
        )


class LocalMediaStore(MediaStore):
    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise ValueError("invalid media key")
        return p

    def _atomic_write(self, key: str, write) -> None:  # noqa: ANN001
        dst = self._path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".part")
        try:
            write(tmp)
            tmp.replace(dst)  # readers never see a partial file
        finally:
            tmp.unlink(missing_ok=True)

    def put_file(self, key: str, path: Path, content_type: str) -> None:
        self._atomic_write(key, lambda tmp: shutil.copyfile(path, tmp))

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self._atomic_write(key, lambda tmp: tmp.write_bytes(data))

    def exists(self, key: str | None) -> bool:
        return bool(key) and self._path(key).is_file()

    def delete_prefix(self, prefix: str) -> None:
        p = self._path(prefix)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)

    @contextmanager
    def local_copy(self, key: str, on_progress=None) -> Iterator[Path]:  # noqa: ANN001
        p = self._path(key)
        if not p.is_file():
            raise FileNotFoundError(key)
        yield p

    def serve(self, key: str, media_type: str, cache: str = NO_STORE) -> Response:
        return FileResponse(
            self._path(key), media_type=media_type, headers={"Cache-Control": cache}
        )


class S3MediaStore(MediaStore):
    """Objects live at s3://<bucket>/<prefix><key>. Credentials come from the standard AWS
    chain (env vars, profile, or the instance/task role); none are stored here."""

    name = "s3"

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        region: str | None = None,
        presign_ttl_sec: int = 300,
        client=None,  # noqa: ANN001 - injectable for tests
    ) -> None:
        import boto3
        from botocore.config import Config

        self.bucket, self.prefix, self.ttl = bucket, prefix.strip("/"), presign_ttl_sec
        if self.prefix:
            self.prefix += "/"
        cfg = Config(retries={"max_attempts": 5, "mode": "standard"}, signature_version="s3v4")
        self.s3 = client or boto3.client(
            "s3", endpoint_url=endpoint_url, region_name=region, config=cfg
        )
        if client is None and region is None and endpoint_url is None:
            # Presigned URLs must be signed for the bucket's own region (a mismatch is a 400
            # in the browser even though server-side calls get redirected and work).
            actual = self._bucket_region()
            if actual and actual != self.s3.meta.region_name:
                # Regional endpoint too: the legacy global host only accepts us-east-1 signatures.
                self.s3 = boto3.client(
                    "s3",
                    region_name=actual,
                    endpoint_url=f"https://s3.{actual}.amazonaws.com",
                    config=cfg,
                )

    def _bucket_region(self) -> str | None:
        """S3 reports the bucket's region in a header even when HeadBucket itself is denied."""
        from botocore.exceptions import ClientError

        try:
            meta = self.s3.head_bucket(Bucket=self.bucket)["ResponseMetadata"]
        except ClientError as e:
            meta = e.response.get("ResponseMetadata", {})
        return meta.get("HTTPHeaders", {}).get("x-amz-bucket-region")

    def _k(self, key: str) -> str:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise ValueError("invalid media key")
        return self.prefix + key

    def put_file(self, key: str, path: Path, content_type: str) -> None:
        # upload_file switches to multipart for large match videos.
        self.s3.upload_file(
            str(path), self.bucket, self._k(key), ExtraArgs={"ContentType": content_type}
        )

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self.s3.put_object(
            Bucket=self.bucket, Key=self._k(key), Body=data, ContentType=content_type
        )

    def exists(self, key: str | None) -> bool:
        if not key:
            return False
        from botocore.exceptions import ClientError

        try:
            self.s3.head_object(Bucket=self.bucket, Key=self._k(key))
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete_prefix(self, prefix: str) -> None:
        base = self._k(prefix)
        keys = [base]
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=base.rstrip("/") + "/"):
            keys += [o["Key"] for o in page.get("Contents", [])]
        for i in range(0, len(keys), 1000):
            self.s3.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": k} for k in keys[i : i + 1000]], "Quiet": True},
            )

    @contextmanager
    def local_copy(self, key: str, on_progress=None) -> Iterator[Path]:  # noqa: ANN001
        """on_progress(done_bytes, total_bytes) is called as the download proceeds."""
        from botocore.exceptions import ClientError

        suffix = Path(key).suffix
        fd = tempfile.NamedTemporaryFile(prefix="ss-media-", suffix=suffix, delete=False)
        fd.close()
        path = Path(fd.name)
        try:
            try:
                cb = None
                if on_progress is not None:
                    total, done = self.size(key), 0

                    def cb(n: int) -> None:
                        nonlocal done
                        done += n
                        on_progress(done, total)

                self.s3.download_file(self.bucket, self._k(key), str(path), Callback=cb)
            except ClientError as e:
                raise FileNotFoundError(key) from e
            yield path
        finally:
            path.unlink(missing_ok=True)

    # ---- direct browser uploads (multipart; parts PUT straight to S3) ----------------------

    def create_multipart(self, key: str, content_type: str) -> str:
        r = self.s3.create_multipart_upload(
            Bucket=self.bucket, Key=self._k(key), ContentType=content_type
        )
        return r["UploadId"]

    def presign_part(self, key: str, upload_id: str, part: int, ttl: int) -> str:
        return self.s3.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": self.bucket,
                "Key": self._k(key),
                "UploadId": upload_id,
                "PartNumber": part,
            },
            ExpiresIn=ttl,
        )

    def complete_multipart(self, key: str, upload_id: str, parts: list[dict]) -> None:
        self.s3.complete_multipart_upload(
            Bucket=self.bucket,
            Key=self._k(key),
            UploadId=upload_id,
            MultipartUpload={
                "Parts": [{"PartNumber": p["PartNumber"], "ETag": p["ETag"]} for p in parts]
            },
        )

    def abort_multipart(self, key: str, upload_id: str) -> None:
        self.s3.abort_multipart_upload(Bucket=self.bucket, Key=self._k(key), UploadId=upload_id)

    def size(self, key: str) -> int:
        return int(self.s3.head_object(Bucket=self.bucket, Key=self._k(key))["ContentLength"])

    def presign(self, key: str, media_type: str, cache: str = NO_STORE) -> str:
        return self.s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": self._k(key),
                "ResponseContentType": media_type,
                "ResponseCacheControl": cache,
            },
            ExpiresIn=self.ttl,
        )

    def serve(self, key: str, media_type: str, cache: str = NO_STORE) -> Response:
        # 307 to a short-lived signed URL: bytes go straight from S3 to the browser. The
        # redirect itself is never cached (the signature expires).
        return RedirectResponse(
            self.presign(key, media_type, cache), 307, headers={"Cache-Control": NO_STORE}
        )


def build_store(settings) -> MediaStore:  # noqa: ANN001
    if settings.media_backend == "s3":
        if not settings.s3_bucket:
            raise ValueError("STREAMSENSE_API_S3_BUCKET is required for the s3 media backend")
        return S3MediaStore(
            settings.s3_bucket,
            settings.s3_prefix,
            settings.s3_endpoint_url,
            settings.s3_region,
            settings.presign_ttl_sec,
        )
    return LocalMediaStore(settings.media_dir)
