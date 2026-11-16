"""Inference backend contract. The worker only talks to this interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from PIL import Image


@dataclass
class FrameResult:
    score: float  # P(quality issue), 0..1
    detections: list[dict] = field(default_factory=list)  # [{"type": DefectType, "severity": 1..5}]
    explanation: str | None = None
    latency_ms: float | None = None
    raw_output: dict | None = None  # the model's original output, kept for provenance
    parse_failed: bool = False
    severity_source: str = "unavailable"  # model | image | unavailable
    location_text: str | None = None  # written description of the affected region


@dataclass
class LocResult:
    method: str
    method_version: str
    grid: list[list[float]]  # rows x cols, higher = stronger defect signal
    peak: dict[str, float]  # {"cx","cy","r"} in 0..1
    region_bounds: list[float]  # [x0, y0, x1, y1] in 0..1


class Backend(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def model_version(self) -> str: ...

    @property
    def device(self) -> str:
        return "cpu"

    @property
    def loaded(self) -> bool:
        return True

    def load(self) -> None:
        """Load weights eagerly (called once by the worker before the first job)."""

    def provenance(self) -> dict:
        """Fields for the ModelVersion record (provider, revision, checkpoint, scoring_method)."""
        return {}

    def localize(self, image: Image.Image) -> "LocResult | None":
        """Heat map for a flagged frame, or None if this backend has no localization method."""
        return None

    @abstractmethod
    def predict(self, images: list[Image.Image]) -> list[FrameResult]:
        """Score + defects + explanation, one result per image, in order (worker thread)."""

    def score(self, images: list[Image.Image]) -> list[float]:
        """P(issue) only: the cheap pass run on every frame (override when cheaper than predict)."""
        return [r.score for r in self.predict(images)]

    def describe(self, images: list[Image.Image]) -> list[FrameResult]:
        """Defects + explanation for frames already flagged by score()."""
        return self.predict(images)
