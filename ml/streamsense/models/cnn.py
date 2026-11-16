"""ResNet-18 adapter: binary head + level-1 multi-label head + severity regression head."""

import csv
import math
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
from omegaconf import DictConfig
from torch import nn

from streamsense.config import project_path
from streamsense.data import taxonomy as tx
from streamsense.data.cache import ArrayCache
from streamsense.data.dataset import canvas_size, load_many
from streamsense.eval.metrics import selection_key
from streamsense.models.base import (
    AdapterPrediction,
    FrameRecord,
    Issue,
    ModelAdapter,
    Prediction,
    PredictionMetadata,
    PredictionScores,
    TrainingResult,
)
from streamsense.utils.hardware import resolve_device

MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


class MultiHeadResNet(nn.Module):
    def __init__(self, n_terms: int, pretrained: bool) -> None:
        super().__init__()
        from torchvision.models import ResNet18_Weights, resnet18

        self.backbone = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1 if pretrained else None)
        self.backbone.fc = nn.Identity()
        self.binary = nn.Linear(512, 1)
        self.terms = nn.Linear(512, n_terms)
        self.severity = nn.Linear(512, 1)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        h = self.backbone(x)
        return self.binary(h).squeeze(1), self.terms(h), self.severity(h).squeeze(1)


def severity_to_target(sev: torch.Tensor) -> torch.Tensor:
    return (sev - 3.0) / 2.0


def target_to_severity(out: torch.Tensor) -> torch.Tensor:
    return (out * 2.0 + 3.0).clamp(1.0, 5.0)


class CNNAdapter(ModelAdapter):
    def __init__(self, cfg: DictConfig) -> None:
        self.cfg = cfg
        if cfg.model.severity_head != "regression":
            raise ValueError("Only the regression severity head is implemented")
        self.tax = tx.Taxonomy.from_config(cfg.taxonomy)
        self.device = torch.device(resolve_device(cfg))
        self.size = canvas_size(cfg.data.image_size, cfg.data.canvas_aspect)
        self.vocab: tuple[str, ...] = ()
        self.model: MultiHeadResNet | None = None
        self._cache: dict[str, np.ndarray] = {}

    # ---- data -------------------------------------------------------------------------
    def _images(self, frames: Sequence[FrameRecord]) -> torch.Tensor:
        """uint8 N x 3 x H x W, decoded once per key and kept in memory."""
        self.warm_cache([f for f in frames if f.key not in self._cache])
        batch = np.stack([self._cache[f.key] for f in frames])
        return torch.from_numpy(batch).permute(0, 3, 1, 2).contiguous()

    def warm_cache(self, frames: Sequence[FrameRecord]) -> int:
        """Load canvases from the disk cache, decoding (and storing) only missing images."""
        disk = ArrayCache(
            project_path(self.cfg, self.cfg.data.cache_dir),
            f"canvas_{self.size[0]}x{self.size[1]}_{self.cfg.data.resize_policy}",
        )
        missing = []
        for f in frames:
            cached = disk.get(f.image_sha256) if f.image_sha256 else None
            if cached is None:
                missing.append(f)
            else:
                self._cache[f.key] = cached
        if missing:
            arrays = load_many([f.image_path for f in missing], self.size,
                               self.cfg.train.num_workers)  # fmt: skip
            for f, a in zip(missing, arrays, strict=True):
                self._cache[f.key] = a
                if f.image_sha256:
                    disk.put(f.image_sha256, a)
        return len(missing)

    def _normalize(self, x: torch.Tensor) -> torch.Tensor:
        x = x.to(self.device, non_blocking=True).float().div_(255)
        return (x - MEAN.to(self.device)) / STD.to(self.device)

    def _autocast(self):
        enabled = self.cfg.train.bf16 and self.device.type == "cuda"
        enabled = enabled and torch.cuda.is_bf16_supported()
        return torch.autocast(self.device.type, dtype=torch.bfloat16, enabled=enabled)

    # ---- training ---------------------------------------------------------------------
    def fit(
        self, train: Sequence[FrameRecord], val: Sequence[FrameRecord], run_dir: Path
    ) -> TrainingResult:
        cfg, t = self.cfg, self.cfg.train
        self.vocab = tx.fit_vocabulary((f.terms for f in train), self.tax)
        self.model = MultiHeadResNet(len(self.vocab), cfg.model.pretrained).to(self.device)
        images = self._images(train)
        y = torch.tensor([f.quality_issue for f in train], dtype=torch.float32)
        terms = torch.tensor(
            [[v in tx.fold_terms(f.terms, self.vocab, self.tax) for v in self.vocab]
             for f in train], dtype=torch.float32,
        )  # fmt: skip
        sev = torch.tensor([np.nan if f.severity is None else f.severity for f in train])
        weight = torch.tensor([cfg.labels.source_weight[f.source] for f in train])
        lw = t.loss_weights

        gen = torch.Generator().manual_seed(cfg.seed)
        steps_per_epoch = math.ceil(len(train) / t.batch_size / t.grad_accum)
        total = t.max_steps or t.epochs * steps_per_epoch
        warmup = max(1, int(t.warmup_ratio * total))
        opt = torch.optim.AdamW(self.model.parameters(), lr=t.lr, weight_decay=t.weight_decay)
        sched = torch.optim.lr_scheduler.LambdaLR(
            opt,
            lambda s: min(1.0, (s + 1) / warmup)
            * 0.5 * (1 + math.cos(math.pi * min(1.0, s / max(1, total)))),
        )  # fmt: skip
        bce = nn.BCEWithLogitsLoss(reduction="none")
        log_path = run_dir / "train_log.csv"
        log = csv.writer(log_path.open("w", newline=""))
        log.writerow(["epoch", "step", "loss", "val_recall_at_p", "val_ap", "lr"])
        writer = None
        if cfg.logging.tensorboard:
            from torch.utils.tensorboard import SummaryWriter

            writer = SummaryWriter(str(run_dir / "tensorboard"))
        val_y = np.array([f.quality_issue for f in val])
        best, best_state, stale, step = None, None, 0, 0
        target = cfg.eval.selection_precision_target
        for epoch in range(t.epochs):
            self.model.train()
            order = torch.randperm(len(train), generator=gen)
            losses = []
            for i in range(0, len(order), t.batch_size):
                idx = order[i : i + t.batch_size]
                x = self._images_augment(images[idx], gen)
                with self._autocast():
                    logit, term_logit, sev_out = self.model(x)
                w = weight[idx].to(self.device)
                yb, tb, sb = (v[idx].to(self.device) for v in (y, terms, sev))
                loss = lw["binary"] * (bce(logit.float(), yb) * w).mean()
                loss = loss + lw["terms"] * (bce(term_logit.float(), tb).mean(1) * w).mean()
                known = ~torch.isnan(sb)
                if known.any():
                    err = (sev_out.float()[known] - severity_to_target(sb[known])) ** 2
                    loss = loss + lw["severity"] * (err * w[known]).mean()
                (loss / t.grad_accum).backward()
                losses.append(loss.item())
                if (i // t.batch_size + 1) % t.grad_accum == 0:
                    opt.step()
                    opt.zero_grad(set_to_none=True)
                    sched.step()
                    step += 1
                if t.max_steps and step >= t.max_steps:
                    break
            val_s = np.array([p.scores.quality_issue for p in self.predict(val)])
            key = selection_key(val_y, val_s, target)
            lr_now = sched.get_last_lr()[0]
            log.writerow([epoch, step, float(np.mean(losses)), key[0], key[1], lr_now])
            if writer:
                writer.add_scalar("train/loss", float(np.mean(losses)), epoch)
                writer.add_scalar("val/recall_at_precision", key[0], epoch)
                writer.add_scalar("val/average_precision", key[1], epoch)
            print(f"epoch {epoch} step {step} loss {np.mean(losses):.4f} "
                  f"val R@P{target} {key[0]:.3f} AP {key[1]:.3f}", flush=True)  # fmt: skip
            if best is None or key > best:
                best, stale = key, 0
                best_state = {k: v.detach().clone() for k, v in self.model.state_dict().items()}
                best_epoch = epoch
            else:
                stale += 1
                if stale >= t.early_stopping_patience:
                    break
            if t.max_steps and step >= t.max_steps:
                break
        if writer:
            writer.close()
        self.model.load_state_dict(best_state)
        return TrainingResult(
            artifact_path=run_dir / "adapter",
            best_validation_metrics_path=log_path,
            details={
                "best_epoch": best_epoch,
                "selection": {"val_recall_at_precision": best[0], "val_ap": best[1],
                              "precision_target": target},
                "vocabulary": list(self.vocab),
                "steps": step,
                "canvas": list(self.size),
            },
        )  # fmt: skip

    def _images_augment(self, x: torch.Tensor, gen: torch.Generator) -> torch.Tensor:
        flip = torch.rand(len(x), generator=gen) < 0.5
        x = torch.where(flip.view(-1, 1, 1, 1), x.flip(-1), x)
        return self._normalize(x)

    # ---- inference --------------------------------------------------------------------
    @torch.no_grad()
    def predict(self, frames: Sequence[FrameRecord]) -> list[AdapterPrediction]:
        if self.model is None:
            raise RuntimeError("Fit or load the CNN before predicting")
        self.model.eval()
        results: list[AdapterPrediction] = []
        version = f"{self.cfg.model.name}@{self.cfg.model.revision}"
        bs = self.cfg.model.batch_size
        for i in range(0, len(frames), bs):
            chunk = frames[i : i + bs]
            start = time.perf_counter()
            with self._autocast():
                logit, term_logit, sev_out = self.model(self._normalize(self._images(chunk)))
            p = torch.sigmoid(logit.float()).cpu().numpy()
            tp = torch.sigmoid(term_logit.float()).cpu().numpy()
            sev = target_to_severity(sev_out.float()).cpu().numpy()
            per_frame_ms = 1000 * (time.perf_counter() - start) / len(chunk)
            for f, pi, ti, si in zip(chunk, p, tp, sev, strict=True):
                results.append(self._output(f, float(pi), ti, float(si), per_frame_ms, version))
        return results

    def _output(
        self, f: FrameRecord, p: float, term_p: np.ndarray, sev: float, ms: float, version: str
    ) -> AdapterPrediction:
        term_scores = {v: float(s) for v, s in zip(self.vocab, term_p, strict=True)}
        crew_scores: dict[str, float] = {}
        for term, s in term_scores.items():
            c = tx.crew_class(term, self.tax)
            crew_scores[c] = max(crew_scores.get(c, 0.0), s)
        issue = p >= self.cfg.model.binary_threshold
        issues: list[Issue] = []
        severity = int(round(sev)) if issue else None
        if issue:
            chosen = [t for t, s in term_scores.items() if s >= self.cfg.model.term_threshold]
            chosen = chosen or [max(term_scores, key=term_scores.get)]
            issues = [
                Issue(tx.crew_class(t, self.tax), t, severity, t in self.tax.weather_terms)
                for t in sorted(chosen, key=lambda t: -term_scores[t])
            ]
        names = ", ".join(i.raw_term for i in issues)
        explanation = f"Detected: {names}." if issues else "No quality issue detected."
        prediction = Prediction(
            quality_issue=bool(issue),
            issues=issues,
            severity=severity,
            explanation=explanation,
            confidence=p,
            metadata=PredictionMetadata(
                model_version=version,
                timestamp=datetime.now(UTC).isoformat(),
                game_id=f.game_id,
                frame_id=f.key,
                latency_ms=ms,
            ),
        )
        scores = PredictionScores(
            key=f.key,
            quality_issue=p,
            score_source="sigmoid",
            terms=term_scores,
            crew_classes=crew_scores,
            severity=sev,
        )
        return AdapterPrediction(prediction, scores)

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        torch.save({"state": self.model.state_dict(), "vocab": list(self.vocab)}, path / "cnn.pt")

    def load(self, path: Path) -> None:
        state = torch.load(path / "cnn.pt", map_location=self.device)
        self.vocab = tuple(state["vocab"])
        self.model = MultiHeadResNet(len(self.vocab), pretrained=False).to(self.device)
        self.model.load_state_dict(state["state"])
