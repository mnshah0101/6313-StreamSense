"""Shared adapter and prediction contracts; no framework imports at this boundary."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Issue:
    name: str
    raw_term: str
    severity: int | None
    weather_related: bool


@dataclass(frozen=True)
class PredictionMetadata:
    model_version: str
    timestamp: str
    game_id: str
    frame_id: str
    latency_ms: float


@dataclass(frozen=True)
class Prediction:
    quality_issue: bool
    issues: list[Issue]
    severity: int | None
    explanation: str
    confidence: float | None
    metadata: PredictionMetadata


@dataclass(frozen=True)
class PredictionScores:
    """Private score sidecar keyed by manifest key, independent of output JSON fields.

    Scores mean probability of an issue/term/class being present. Missing scores are
    None or absent keys, never fabricated zeros. Calibration must track score_source.
    """

    key: str
    quality_issue: float | None
    score_source: str
    terms: dict[str, float] = field(default_factory=dict)
    crew_classes: dict[str, float] = field(default_factory=dict)
    severity: float | None = None  # continuous severity estimate, if the model has one
    parse_failed: bool = False


@dataclass(frozen=True)
class FrameRecord:
    key: str
    game_id: str
    frame_idx: int
    image_path: Path
    quality_issue: bool
    terms: tuple[str, ...]
    severity: int | None
    source: str
    description: str | None = None
    image_sha256: str | None = None  # content address for decode/feature caches


@dataclass(frozen=True)
class AdapterPrediction:
    output: Prediction
    scores: PredictionScores


@dataclass(frozen=True)
class TrainingResult:
    artifact_path: Path
    best_validation_metrics_path: Path | None
    details: dict[str, Any] = field(default_factory=dict)


class ModelAdapter(ABC):
    """Model-specific training and preprocessing live behind this interface.

    Evaluation code will pass all predictions through the shared normalizer and
    metrics module. Adapters must not implement their own metrics.
    """

    @abstractmethod
    def fit(
        self, train: Sequence[FrameRecord], val: Sequence[FrameRecord], run_dir: Path
    ) -> TrainingResult:
        """Train/fit using train only, selecting checkpoints using validation."""

    @abstractmethod
    def predict(self, frames: Sequence[FrameRecord]) -> list[AdapterPrediction]:
        """Return one prediction and score record per input frame, in input order."""

    @abstractmethod
    def save(self, path: Path) -> None:
        """Persist only this adapter's fitted state and reproducibility metadata."""

    @abstractmethod
    def load(self, path: Path) -> None:
        """Restore adapter state using its configured base-model revision."""

    def warm_cache(self, frames: Sequence[FrameRecord]) -> int:
        """Precompute deterministic per-image inputs (decodes, features); returns new entries."""
        return 0
