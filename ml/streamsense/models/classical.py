"""BRISQUE/NIQE adapter: no-reference IQA features + logistic regression. Binary only."""

import pickle
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
from omegaconf import DictConfig
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from streamsense.config import project_path
from streamsense.data.cache import ArrayCache
from streamsense.data.dataset import load_native
from streamsense.models.base import (
    AdapterPrediction,
    FrameRecord,
    ModelAdapter,
    Prediction,
    PredictionMetadata,
    PredictionScores,
    TrainingResult,
)
from streamsense.utils.hardware import resolve_device


class ClassicalAdapter(ModelAdapter):
    def __init__(self, cfg: DictConfig) -> None:
        self.cfg = cfg
        self.metric_names = list(cfg.model.classical_metrics)
        if cfg.model.classical_estimator != "logistic_regression":
            raise ValueError("Only logistic_regression is implemented for the classical model")
        self.device = torch.device(resolve_device(cfg))
        self.pipeline = None
        self._features: dict[str, np.ndarray] = {}
        self._seconds: dict[str, float] = {}
        self._metrics = None

    def _iqa(self):
        if self._metrics is None:
            import pyiqa

            self._metrics = [
                pyiqa.create_metric(n, device=self.device, as_loss=False) for n in self.metric_names
            ]
        return self._metrics

    def features(self, frames: Sequence[FrameRecord]) -> np.ndarray:
        """One row of [brisque, niqe, ...] per frame, computed once and cached by key."""
        self.warm_cache(frames)
        return np.stack([self._features[f.key] for f in frames])

    def warm_cache(self, frames: Sequence[FrameRecord]) -> int:
        """Features are cached on disk by image SHA-256, metric list, size cap and pyiqa version.

        Latency is measured only when a feature is computed in this process; cached
        predictions report NaN latency rather than a misleading near-zero number.
        """
        from importlib.metadata import version

        disk = ArrayCache(
            project_path(self.cfg, self.cfg.data.cache_dir),
            f"iqa_{'-'.join(self.metric_names)}_max{self.cfg.model.classical_max_side}"
            f"_pyiqa{version('pyiqa')}",
        )
        new = 0
        for f in frames:
            if f.key in self._features:
                continue
            cached = disk.get(f.image_sha256) if f.image_sha256 else None
            if cached is not None:
                self._features[f.key] = cached
                continue
            start = time.perf_counter()
            image = load_native(f.image_path, self.cfg.model.classical_max_side)
            x = torch.from_numpy(image).permute(2, 0, 1)[None].float().div(255).to(self.device)
            with torch.no_grad():
                values = np.array([float(m(x).item()) for m in self._iqa()])
            self._features[f.key] = values
            self._seconds[f.key] = time.perf_counter() - start
            if f.image_sha256:
                disk.put(f.image_sha256, values)
            new += 1
        return new

    def fit(
        self, train: Sequence[FrameRecord], val: Sequence[FrameRecord], run_dir: Path
    ) -> TrainingResult:
        x = self.features(train)
        if not np.isfinite(x).all():
            raise ValueError("Non-finite IQA feature; inspect the offending images")
        y = np.array([f.quality_issue for f in train])
        weights = np.array([self.cfg.labels.source_weight[f.source] for f in train])
        self.pipeline = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
        self.pipeline.fit(x, y, logisticregression__sample_weight=weights)
        lr = self.pipeline[-1]
        return TrainingResult(
            artifact_path=run_dir / "adapter",
            best_validation_metrics_path=None,
            details={
                "features": self.metric_names,
                "coef_standardized": lr.coef_[0].tolist(),
                "intercept": float(lr.intercept_[0]),
                "n_train": len(train),
            },
        )

    def predict(self, frames: Sequence[FrameRecord]) -> list[AdapterPrediction]:
        if self.pipeline is None:
            raise RuntimeError("Fit or load the classical model before predicting")
        x = self.features(frames)
        prob = self.pipeline.predict_proba(x)[:, 1]
        version = f"{self.cfg.model.name}@{self.cfg.model.revision}"
        out = []
        for f, p, feats in zip(frames, prob, x, strict=True):
            issue = bool(p >= self.cfg.model.binary_threshold)
            detail = ", ".join(
                f"{n}={v:.2f}" for n, v in zip(self.metric_names, feats, strict=True)
            )
            prediction = Prediction(
                quality_issue=issue,
                issues=[],
                severity=None,
                explanation=f"No-reference IQA features: {detail}.",
                confidence=float(p),
                metadata=PredictionMetadata(
                    model_version=version,
                    timestamp=datetime.now(UTC).isoformat(),
                    game_id=f.game_id,
                    frame_id=f.key,
                    latency_ms=1000 * self._seconds.get(f.key, float("nan")),
                ),
            )
            scores = PredictionScores(key=f.key, quality_issue=float(p), score_source="logistic")
            out.append(AdapterPrediction(prediction, scores))
        return out

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        with (path / "classical.pkl").open("wb") as fh:
            pickle.dump({"pipeline": self.pipeline, "metrics": self.metric_names}, fh)

    def load(self, path: Path) -> None:
        with (path / "classical.pkl").open("rb") as fh:
            state = pickle.load(fh)
        self.pipeline, self.metric_names = state["pipeline"], state["metrics"]
