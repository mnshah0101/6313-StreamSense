"""Real model backend: a playonsports training run (VLM + LoRA adapter) behind the Backend API.

Point STREAMSENSE_API_RUN_DIR at outputs/<experiment>/<run> and
STREAMSENSE_API_STREAMSENSE_REPO at the playonsports checkout. The run's own resolved config
(run_record.json) rebuilds the exact model, prompt and taxonomy it was trained with, and the
adapter loader refuses a checkpoint trained on a different base-model revision.
"""

import json
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

from app.defects import CREW_TO_DEFECT, SPATIAL_DEFECTS, merge_detections
from app.inference.base import Backend, FrameResult, LocResult


class StreamSenseBackend(Backend):
    name = "streamsense"

    def __init__(
        self,
        run_dir: Path,
        repo: Path | None,
        device: str | None,
        batch_size: int,
        binary_threshold: float,
        max_new_tokens: int | None = None,
    ) -> None:
        self.run_dir = Path(run_dir).resolve()
        self.repo = Path(repo).resolve() if repo else None
        self.device_override = device
        self.batch_size = batch_size
        self.binary_threshold = binary_threshold
        self.max_new_tokens = max_new_tokens
        self.adapter = None
        self.cfg = None
        self._tmp = Path(tempfile.mkdtemp(prefix="streamsense-api-"))
        record = json.loads((self.run_dir / "run_record.json").read_text())
        self._record = record
        m = record["resolved_config"]["model"]
        self._version = f"{m['name']}@{m['revision'][:8]}+{self.run_dir.name}"

    @property
    def model_version(self) -> str:
        return self._version

    @property
    def device(self) -> str:
        return (
            str(self.adapter.device) if self.adapter is not None else (self.device_override or "?")
        )

    @property
    def loaded(self) -> bool:
        return self.adapter is not None

    def load(self) -> None:
        if self.adapter is not None:
            return
        if self.repo and str(self.repo) not in sys.path:
            sys.path.insert(0, str(self.repo))
        from omegaconf import OmegaConf
        from streamsense.models.registry import build_adapter

        cfg = OmegaConf.create(self._record["resolved_config"])
        overrides = {
            "model": {
                "batch_size": self.batch_size,
                "binary_threshold": self.binary_threshold,
                **({"max_new_tokens": self.max_new_tokens} if self.max_new_tokens else {}),
            },
            # Paths in the run config are relative to the training repo; the decode cache
            # goes to a private temp dir so the service never writes into that repo.
            "run": {"project_root": str(self.repo or self.run_dir)},
            "data": {"cache_dir": str(self._tmp / "cache")},
        }
        if self.device_override:
            overrides["hardware"] = {"device": self.device_override}
        cfg = OmegaConf.merge(cfg, overrides)
        adapter = build_adapter(cfg)
        adapter.load(self.run_dir / "adapter")
        # Frames reach the model from memory: the adapter's own _image() reads a file and
        # caches the resized array on disk, which costs a PNG round-trip per live frame.
        # This instance attribute shadows it with the same resize, without any file I/O.
        self._frames: dict[str, Image.Image] = {}
        adapter._image = lambda f: self._frames[f.key]
        self.cfg, self.adapter = cfg, adapter

    def _resize(self, im: Image.Image) -> Image.Image:
        """Exactly the training preprocessing (streamsense.models.vlm.load_frame)."""
        im = im.convert("RGB")
        side = self.cfg.model.image_max_side
        if side and max(im.size) > side:
            scale = side / max(im.size)
            im = im.resize(
                (round(im.width * scale), round(im.height * scale)), Image.Resampling.BICUBIC
            )
        return im

    def _records(self, images: list[Image.Image], resized: bool = False) -> list:
        from streamsense.models.base import FrameRecord

        self._frames = {}
        recs = []
        for i, im in enumerate(images):
            key = f"api/frame_{i}"
            self._frames[key] = im if resized else self._resize(im)
            recs.append(
                FrameRecord(
                    key=key,
                    game_id="api",
                    frame_idx=i,
                    image_path=Path("/dev/null"),
                    quality_issue=False,
                    terms=(),
                    severity=None,
                    source="user",
                )
            )
        return recs

    def predict(self, images: list[Image.Image]) -> list[FrameResult]:
        self.load()
        start = time.perf_counter()  # includes resize: it is part of every live frame's cost
        records = self._records(images)
        preds = self.adapter.predict(records)
        per_frame_ms = 1000 * (time.perf_counter() - start) / max(1, len(records))
        out = []
        for p in preds:
            o = p.output
            dets = []
            if o.quality_issue:
                for issue in o.issues:
                    t = CREW_TO_DEFECT.get(issue.name)
                    if t is None:
                        continue
                    sev = issue.severity or o.severity or 2
                    dets.append({"type": t, "severity": int(min(5, max(1, sev)))})
            dets = merge_detections(dets)
            score = p.scores.quality_issue if p.scores.quality_issue is not None else 0.0
            raw = {
                "quality_issue": o.quality_issue,
                "severity": o.severity,
                "issues": [vars(i) for i in o.issues],
                "explanation": o.explanation,
            }
            out.append(
                FrameResult(
                    score=float(score),
                    detections=dets,
                    explanation=o.explanation or None,
                    latency_ms=per_frame_ms,
                    raw_output=raw,
                    parse_failed=p.scores.parse_failed,
                    # Training labels rate severity per image, not per defect.
                    severity_source="image",
                )
            )
        return out

    def score(self, images: list[Image.Image]) -> list[float]:
        return [r.score for r in self._score_only(images)]

    def describe(self, images: list[Image.Image]) -> list[FrameResult]:
        return self.predict(images)

    def provenance(self) -> dict:
        m = self._record["resolved_config"]["model"]
        return {
            "provider": m["model_id"],
            "revision": m["revision"],
            "checkpoint": str(self.run_dir / "adapter"),
            "scoring_method": "first_token_p_true",
        }

    def localize(self, image: Image.Image) -> LocResult:
        """Occlusion heat map: grey out each of 4x6 tiles and measure the drop in log-odds of
        an issue (the E-13 probe method). 25 score-only forward passes per frame."""
        import numpy as np

        from app.inference.dummy import grid_to_loc

        d = self.occlusion_heat(image)
        return grid_to_loc("occlusion_logodds", "1", np.array(d["grid"]))

    def occlusion_heat(self, im: Image.Image, rows: int = 4, cols: int = 6) -> dict | None:
        """Grey out each tile and measure the drop in log-odds (E-13 probe method).

        rows*cols+1 forward passes; returns the hottest tile as {cx, cy, r} plus the grid.
        """
        import math

        import numpy as np

        self.load()
        # Occlude in the model's input resolution: one resize instead of 25.
        base = np.asarray(self._resize(im)).copy()
        h, w = base.shape[:2]
        variants = [Image.fromarray(base)]
        for r in range(rows):
            for c in range(cols):
                a = base.copy()
                a[r * h // rows : (r + 1) * h // rows, c * w // cols : (c + 1) * w // cols] = 128
                variants.append(Image.fromarray(a))
        scores = [x.score for x in self._score_only(variants, resized=True)]
        eps = 1e-6

        def logit(p: float) -> float:
            p = min(1 - eps, max(eps, p))
            return math.log(p / (1 - p))

        drops = np.array([logit(scores[0]) - logit(s) for s in scores[1:]]).reshape(rows, cols)
        r, c = np.unravel_index(int(drops.argmax()), drops.shape)
        return {
            "cx": (c + 0.5) / cols,
            "cy": (r + 0.5) / rows,
            "r": 0.5 / max(rows, cols) * 1.5,
            "grid": drops.round(4).tolist(),
        }

    def _score_only(self, images: list[Image.Image], resized: bool = False) -> list[FrameResult]:
        """P(issue) without generation (alerts need only this; heat maps use it 25x)."""
        self.load()
        recs = self._records(images, resized)
        return [FrameResult(float(s)) for s in self.adapter.score(recs)]


def spatial(dets: list[dict]) -> bool:
    return any(d["type"] in SPATIAL_DEFECTS for d in dets)
