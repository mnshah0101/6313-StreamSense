"""Deterministic stand-in for the model: no GPU, no weights.

Real images get crude but plausible results from pixel statistics (dark -> Low light,
blown out -> Overexposure, low Laplacian variance -> Blur), so an upload exercises the whole
pipeline (scoring, alerts, heat maps) without a GPU. Results are tagged dummy@0.1.
"""

import time

import numpy as np
from PIL import Image

from app.inference.base import Backend, FrameResult, LocResult


class DummyBackend(Backend):
    name = "dummy"

    def __init__(self, latency_ms: float = 0.0) -> None:
        self.latency_ms = latency_ms  # optional artificial delay per frame, for demos

    @property
    def model_version(self) -> str:
        return "dummy@0.1"

    def predict(self, images: list[Image.Image]) -> list[FrameResult]:
        return [self._one(im) for im in images]

    def _one(self, im: Image.Image) -> FrameResult:
        start = time.perf_counter()
        g = np.asarray(im.convert("L").resize((320, 180)), dtype=np.float32)
        mean = float(g.mean())
        bright = float((g > 245).mean())
        lap = g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
        sharp = float(lap.var())
        dets: list[dict] = []
        if mean < 50:
            dets.append({"type": "Low light", "severity": _sev((50 - mean) / 50)})
        if bright > 0.15:
            dets.append({"type": "Overexposure", "severity": _sev(bright)})
        if sharp < 60:
            dets.append({"type": "Blur", "severity": _sev((60 - sharp) / 60)})
        score = 0.08 if not dets else min(0.99, 0.5 + 0.1 * max(d["severity"] for d in dets))
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000)
        expl = (
            f"dummy: mean luma {mean:.0f}, clipped {bright:.0%}, sharpness {sharp:.0f}"
            if dets
            else None
        )
        raw = {"mean_luma": mean, "clipped": bright, "sharpness": sharp}
        return FrameResult(
            score,
            dets,
            expl,
            1000 * (time.perf_counter() - start),
            raw_output=raw,
            severity_source="model",
        )

    def provenance(self) -> dict:
        return {"provider": "streamsense-api", "scoring_method": "pixel_statistics"}

    def localize(self, image: Image.Image) -> LocResult:
        """Least-detailed tiles are 'hot' (a crude stand-in for a blur/smear location)."""
        g = np.asarray(image.convert("L").resize((320, 180)), dtype=np.float32)
        lap = np.abs(g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:])
        rows, cols = 4, 6
        h, w = lap.shape
        detail = np.array(
            [
                [
                    lap[
                        r * h // rows : (r + 1) * h // rows, c * w // cols : (c + 1) * w // cols
                    ].mean()
                    for c in range(cols)
                ]
                for r in range(rows)
            ]
        )
        grid = 1 - detail / max(float(detail.max()), 1e-6)
        return grid_to_loc("dummy_low_detail", "1", grid)


def _sev(x: float) -> int:
    return int(min(5, max(1, round(1 + 4 * x))))


def grid_to_loc(method: str, version: str, grid: np.ndarray) -> LocResult:
    """Hottest tile -> peak circle and region bounds (normalised to 0..1)."""
    rows, cols = grid.shape
    r, c = np.unravel_index(int(grid.argmax()), grid.shape)
    return LocResult(
        method=method,
        method_version=version,
        grid=np.round(grid, 4).tolist(),
        peak={"cx": (c + 0.5) / cols, "cy": (r + 0.5) / rows, "r": 0.75 / max(rows, cols)},
        region_bounds=[c / cols, r / rows, (c + 1) / cols, (r + 1) / rows],
    )
