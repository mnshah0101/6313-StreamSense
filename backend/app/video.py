"""Decode uploads and sample one frame every N seconds. Format is checked by decoding,
not by the client's content type."""

import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

IMAGE_FORMATS = {"JPEG", "PNG"}


class MediaError(Exception):
    """Unreadable or out-of-policy media. `code` is a stable, user-safe failure code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class Probe:
    kind: str  # image | video
    duration_sec: float
    width: int
    height: int


def probe(path: Path) -> Probe:
    try:
        with Image.open(path) as im:
            if im.format not in IMAGE_FORMATS:
                raise MediaError("unsupported_format", f"Unsupported image format {im.format}")
            return Probe("image", 0.0, im.width, im.height)
    except UnidentifiedImageError:
        pass
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise MediaError("unsupported_format", "Not a readable image or video file")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        ok, _ = cap.read()
        if not ok or fps <= 0 or w == 0:
            raise MediaError("decode_failed", "Video has no decodable frames")
        return Probe("video", n / fps, w, h)
    finally:
        cap.release()


def sample(
    path: Path, interval_sec: float, start_index: int = 0
) -> Iterator[tuple[int, int, Image.Image]]:
    """Yield (index, timestamp_ms, RGB image) for frames at 0, interval, 2*interval, ...

    Seeks by timestamp, so a resumed job can start at `start_index` without decoding the
    frames it already processed.
    """
    p = probe(path)
    if p.kind == "image":
        if start_index == 0:
            with Image.open(path) as im:
                yield 0, 0, im.convert("RGB")
        return
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        i = start_index
        while True:
            t_ms = int(round(i * interval_sec * 1000))
            if t_ms >= p.duration_sec * 1000:
                break
            cap.set(cv2.CAP_PROP_POS_MSEC, t_ms)
            ok, bgr = cap.read()
            if not ok:
                break
            yield i, t_ms, Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            i += 1
    finally:
        cap.release()


def frame_count(p: Probe, interval_sec: float) -> int:
    """Sampled timestamps strictly inside the video: 0, interval, ... < duration."""
    if p.kind == "image":
        return 1
    return max(1, math.ceil(p.duration_sec / interval_sec - 1e-9))


def poster(path: Path, at_fraction: float = 0.1, max_tries: int = 5) -> Image.Image:
    """A representative frame: ~10% into a video (streams often open on black or slates),
    stepping forward past near-black frames. Images are their own poster."""
    p = probe(path)
    if p.kind == "image":
        with Image.open(path) as im:
            return im.convert("RGB")
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(path))
    try:
        first = None
        for i in range(max_tries):
            t = p.duration_sec * min(0.9, at_fraction + i * 0.1)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, bgr = cap.read()
            if not ok:
                continue
            im = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            first = first or im
            if float(np.asarray(im.convert("L")).mean()) >= 16:
                return im
        if first is None:
            raise MediaError("decode_failed", "Video has no decodable frames")
        return first
    finally:
        cap.release()
