"""Hugging Face image-text-to-text adapter (Qwen3.5-0.8B, Qwen2.5-VL-3B, ...).

train=none is zero-shot; train=lora fine-tunes LoRA adapters on the language model only.

Generation starts from a forced answer prefix (`model.answer_prefix`, e.g. '{"quality_issue":').
The first generated token's probability of "true" vs "false" is the issue score used for
PR curves and precision-first thresholds; the model's self-reported confidence is kept in
the output but is not used as the score. `score()` computes that probability in one forward
pass; `predict()` reuses it, forces the matching first token, then generates the rest.
"""

import csv
import json
import math
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
from omegaconf import DictConfig
from PIL import Image
from transformers import LogitsProcessorList

from streamsense.config import project_path
from streamsense.data import taxonomy as tx
from streamsense.data.cache import ArrayCache
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
from streamsense.models.output_parser import parse_output
from streamsense.train.collate_vlm import (
    Example,
    answer_span,
    class_mask_tail,
    collate,
    target_segments,
    tokenize_segments_with_classes,
)
from streamsense.utils.hardware import resolve_device

DTYPES = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}


def load_frame(path: Path, max_side: int | None) -> Image.Image:
    with Image.open(path) as im:
        im = im.convert("RGB")
        if max_side and max(im.size) > max_side:
            scale = max_side / max(im.size)
            im = im.resize((round(im.width * scale), round(im.height * scale)),
                           Image.Resampling.BICUBIC)  # fmt: skip
        return im


def _layer_index(name: str) -> int:
    """Index N in '...layers.N...' or '...blocks.N...' (the language/vision block number)."""
    parts = name.split(".")
    for key in ("layers", "blocks"):
        if key in parts:
            return int(parts[parts.index(key) + 1])
    raise ValueError(f"No layer index in {name}")


class BooleanFirstToken:
    """Logits processor: at the first generated step, record P(true) vs P(false) from the
    unconstrained distribution, then allow only true/false tokens. Later steps are free.

    This guarantees a boolean quality_issue after the forced '{"quality_issue":' prefix;
    the rest of the JSON is written by the model and still goes through the parser.
    """

    def __init__(
        self,
        true_ids: list[int],
        false_ids: list[int],
        prompt_len: int,
        forced: list[bool] | None = None,
    ) -> None:
        self.true_ids, self.false_ids, self.prompt_len = true_ids, false_ids, prompt_len
        self.forced = forced  # per row: True -> only true tokens, False -> only false tokens
        self.p_true: torch.Tensor | None = None
        self.unconstrained_mass: torch.Tensor | None = None

    def __call__(self, input_ids: torch.Tensor, scores: torch.Tensor) -> torch.Tensor:
        if input_ids.shape[1] != self.prompt_len:
            return scores
        probs = torch.softmax(scores.float(), dim=-1)
        p_t = probs[:, self.true_ids].sum(1)
        p_f = probs[:, self.false_ids].sum(1)
        self.p_true = (p_t / (p_t + p_f).clamp_min(1e-12)).cpu()
        self.unconstrained_mass = (p_t + p_f).cpu()
        allowed = torch.full_like(scores, float("-inf"))
        for row in range(scores.shape[0]):
            if self.forced is None:
                ids = self.true_ids + self.false_ids
            else:
                ids = self.true_ids if self.forced[row] else self.false_ids
            allowed[row, ids] = scores[row, ids]
        return allowed


class VLMAdapter(ModelAdapter):
    def __init__(self, cfg: DictConfig) -> None:
        self.cfg = cfg
        self.tax = tx.Taxonomy.from_config(cfg.taxonomy)
        self.device = torch.device(resolve_device(cfg))
        self.vocab: tuple[str, ...] = ()
        self.model = None
        self.processor = None
        self.parse_stats: dict[str, int] = {}

    def _load(self) -> None:
        if self.model is not None:
            return
        from transformers import AutoModelForImageTextToText, AutoProcessor

        m = self.cfg.model
        try:
            self.processor = AutoProcessor.from_pretrained(m.model_id, revision=m.revision)
            self.model = AutoModelForImageTextToText.from_pretrained(
                m.model_id, revision=m.revision, dtype=DTYPES[m.dtype],
                trust_remote_code=m.trust_remote_code,
            ).to(self.device).eval()  # fmt: skip
        except Exception as exc:
            hint = f" Try model={m.fallback}." if m.fallback else ""
            raise RuntimeError(f"Cannot load {m.model_id}@{m.revision}: {exc!r}.{hint}") from exc
        self.processor.tokenizer.padding_side = "left"
        tok = self.processor.tokenizer
        self.true_ids = self._first_ids(tok, ("true", " true", "True", " True"))
        self.false_ids = self._first_ids(tok, ("false", " false", "False", " False"))

    def _image(self, f: FrameRecord) -> Image.Image:
        """Resized RGB frame, cached on disk by image SHA-256."""
        side = self.cfg.model.image_max_side
        if not hasattr(self, "_disk"):
            root = project_path(self.cfg, self.cfg.data.cache_dir)
            self._disk = ArrayCache(root, f"rgb_max{side}")
        array = self._disk.get_or_compute(
            f.image_sha256, lambda: np.asarray(load_frame(f.image_path, side))
        )
        return Image.fromarray(array)

    @staticmethod
    def _first_ids(tok, words: Sequence[str]) -> list[int]:
        return sorted({tok.encode(w, add_special_tokens=False)[0] for w in words})

    def _prompt_text(self) -> str:
        mapping = "; ".join(f"{t} -> {tx.crew_class(t, self.tax)}" for t in self.vocab)
        return self.cfg.prompt.user.format(
            terms=", ".join(self.vocab),
            crew_classes=", ".join(self.tax.crew_classes),
            term_mapping=mapping,
        )

    def _texts(self, n: int) -> list[str]:
        conversation = [
            {"role": "system", "content": [{"type": "text", "text": self.cfg.prompt.system}]},
            {"role": "user", "content": [
                {"type": "image"}, {"type": "text", "text": self._prompt_text()},
            ]},
        ]  # fmt: skip
        text = self.processor.apply_chat_template(
            conversation, tokenize=False, add_generation_prompt=True,
            enable_thinking=self.cfg.model.thinking,
        )  # fmt: skip
        return [text + self.cfg.model.answer_prefix] * n

    def fit(
        self, train: Sequence[FrameRecord], val: Sequence[FrameRecord], run_dir: Path
    ) -> TrainingResult:
        """Zero-shot fits only the train-split vocabulary used in the prompt; lora trains."""
        self.vocab = tx.fit_vocabulary((f.terms for f in train), self.tax)
        self._load()
        if self.cfg.train.name == "lora":
            return self._train_lora(train, val, run_dir)
        if self.cfg.train.name != "none":
            raise ValueError(f"VLM supports train=none or train=lora, not {self.cfg.train.name}")
        return TrainingResult(
            artifact_path=run_dir / "adapter",
            best_validation_metrics_path=None,
            details={"mode": "zero_shot", "vocabulary": list(self.vocab),
                     "prompt_version": self.cfg.prompt.version,
                     "user_prompt": self._prompt_text(),
                     "answer_prefix": self.cfg.model.answer_prefix},
        )  # fmt: skip

    # ---- LoRA ---------------------------------------------------------------------------
    def lora_targets(self) -> list[str]:
        """Full names of the Linear layers that get LoRA adapters.

        Language: leaf names in `target_modules` under `language_scope`, optionally limited to
        layer indices `layers: [first, last]` (inclusive). Vision: leaf names in
        `vision_target_modules` under `vision_scope` (empty = vision gets no adapters). Leaf
        names alone are not safe: Qwen2.5-VL's vision blocks also have gate/up/down_proj.
        """
        lo = self.cfg.train.lora
        linear = [n for n, mod in self.model.named_modules() if isinstance(mod, torch.nn.Linear)]

        def pick(scope: str, wanted: set[str]) -> list[str]:
            scope = scope.rstrip(".") + "."
            return [n for n in linear if n.startswith(scope) and n.rsplit(".", 1)[-1] in wanted]

        language = pick(lo.language_scope, set(lo.target_modules))
        if lo.layers is not None:
            first, last = lo.layers
            language = [n for n in language if first <= _layer_index(n) <= last]
        if not language:
            raise ValueError(f"No language LoRA targets match {sorted(lo.target_modules)} "
                             f"in layers {lo.layers}")  # fmt: skip
        if any(m in n for n in language for m in (".visual.", ".vision_tower.", ".vision_model.")):
            raise AssertionError("Language LoRA targets must not include the vision encoder")
        vision = pick(lo.vision_scope, set(lo.vision_target_modules))
        if lo.vision_target_modules and not vision:
            raise ValueError(f"No vision LoRA targets match {sorted(lo.vision_target_modules)}")
        return language + vision

    def _wrap_lora(self) -> dict[str, int]:
        from peft import LoHaConfig, LoKrConfig, LoraConfig, get_peft_model

        lo = self.cfg.train.lora
        targets = self.lora_targets()
        skipped = []
        if lo.style == "dora":
            # DoRA divides by each output row's weight norm; an all-zero row gives 0/0 = NaN
            # on the first forward (Qwen3.5-0.8B layer 0 in_proj_qkv has 14 such rows).
            modules = dict(self.model.named_modules())
            skipped = [n for n in targets if (modules[n].weight.norm(dim=1) == 0).any()]
            targets = [n for n in targets if n not in skipped]
        modules_to_save = [lo.projector_module] if lo.train_projector else None
        common = dict(r=lo.r, target_modules=targets, modules_to_save=modules_to_save)
        if lo.style in ("lora", "dora", "rslora"):
            config = LoraConfig(
                **common, lora_alpha=lo.alpha, lora_dropout=lo.dropout, bias="none",
                use_dora=lo.style == "dora", use_rslora=lo.style == "rslora",
            )  # fmt: skip
        elif lo.style in ("loha", "lokr"):
            cls = LoHaConfig if lo.style == "loha" else LoKrConfig
            config = cls(**common, alpha=lo.alpha, rank_dropout=lo.dropout)
        else:
            raise ValueError(f"Unknown train.lora.style {lo.style!r}")
        self.model = get_peft_model(self.model, config)
        trainable = [n for n, p in self.model.named_parameters() if p.requires_grad]
        vision_ok = bool(lo.vision_target_modules) or lo.train_projector
        vision_markers = (".visual.", ".vision_tower.", ".vision_model.")
        if not vision_ok and any(m in n for n in trainable for m in vision_markers):
            raise AssertionError(f"Vision parameters are trainable: {trainable[:5]}")
        counts = {
            "target_modules": len(targets),
            "dora_skipped_zero_norm_modules": len(skipped),
            "trainable_params": sum(p.numel() for p in self.model.parameters() if p.requires_grad),
            "total_params": sum(p.numel() for p in self.model.parameters()),
        }
        for p_ in self.model.parameters():
            if p_.requires_grad:
                p_.data = p_.data.float()  # fp32 master weights for adapters
        return counts

    def _targets(
        self, frames: Sequence[FrameRecord]
    ) -> list[tuple[list[int], list[bool], list[bool]]]:
        """Tokenized answer, loss mask and class-name mask per frame (kept for the whole run)."""
        tok = self.processor.tokenizer
        use_description = self.cfg.labels.description_as_explanation
        return [
            tokenize_segments_with_classes(
                tok, target_segments(f, self.vocab, self.tax, use_description, tok.eos_token)
            )  # fmt: skip
            for f in frames
        ]

    def _examples(
        self,
        frames: Sequence[FrameRecord],
        targets: Sequence[tuple[list[int], list[bool], list[bool]]],
    ) -> list[Example]:
        """Processor outputs are built per batch: holding pixel tensors for every training
        image (~11 MB each in fp32) exceeds a 16 GB job allocation."""
        prompt_text = self._texts(1)[0]
        return [
            Example(
                dict(
                    self.processor(
                        text=[prompt_text], images=[[self._image(f)]], return_tensors="pt"
                    )
                ),  # fmt: skip
                ids,
                mask,
                self.cfg.labels.source_weight[f.source],
                classes,
            )
            for f, (ids, mask, classes) in zip(frames, targets, strict=True)
        ]

    def _order(self, frames: Sequence[FrameRecord], gen: torch.Generator) -> list[int]:
        n = len(frames)
        if not self.cfg.train.class_balanced_sampling:
            return torch.randperm(n, generator=gen).tolist()
        y = torch.tensor([f.quality_issue for f in frames], dtype=torch.float)
        w = torch.where(y > 0, 0.5 / y.sum().clamp_min(1), 0.5 / (1 - y).sum().clamp_min(1))
        return torch.multinomial(w, n, replacement=True, generator=gen).tolist()

    def _loss(self, batch: dict[str, torch.Tensor], labels: torch.Tensor, weights: torch.Tensor,
              span: int, class_mask: torch.Tensor | None = None,
              ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:  # fmt: skip
        """Per example: mean answer-token CE + decision_loss_weight x CE of the true/false token
        + class_loss_weight x mean CE of the crew-class name tokens (issue frames only).

        The true/false token is ~1 of ~50 answer tokens, so plain token-averaged CE barely
        trains the decision (observed: train P(true) 0.175 pos vs 0.156 neg). It is the first
        trainable label in every row. Batches are left-padded, so logits are only computed for
        the last `span` positions (the answers), not the ~800-token prompt.
        Class names are ~5 of ~50 answer tokens and otherwise only get their share of the
        token average. Returns (weighted loss, mean decision-token CE, mean class-token CE).
        """
        with torch.autocast(
            self.device.type,
            dtype=torch.bfloat16,
            enabled=self.cfg.train.bf16 and self.device.type == "cuda",
        ):
            logits = self.model(**batch, use_cache=False, logits_to_keep=span).logits
        logits, labels = logits[:, :-1].float(), labels[:, -(span - 1) :]
        ce = torch.nn.functional.cross_entropy(
            logits.reshape(-1, logits.shape[-1]), labels.reshape(-1),
            ignore_index=-100, reduction="none",
        ).view(labels.shape)  # fmt: skip
        trainable = labels != -100
        n_tok = trainable.sum(1).clamp_min(1)
        first = trainable.float().argmax(1)  # index of the true/false token in each row
        decision = ce.gather(1, first[:, None]).squeeze(1)
        per_example = ce.sum(1) / n_tok + self.cfg.train.decision_loss_weight * decision
        cls_ce = torch.zeros((), device=ce.device)
        if class_mask is not None:
            cm = class_mask.to(ce.device) & trainable
            n_cls = cm.sum(1)
            per_cls = (ce * cm).sum(1) / n_cls.clamp_min(1)
            per_example = per_example + self.cfg.train.class_loss_weight * per_cls
            has = n_cls > 0
            if has.any():
                cls_ce = per_cls[has].mean().detach()
        return (per_example * weights).sum() / weights.sum(), decision.mean().detach(), cls_ce

    def _train_lora(
        self, train: Sequence[FrameRecord], val: Sequence[FrameRecord], run_dir: Path
    ) -> TrainingResult:
        cfg, t = self.cfg, self.cfg.train
        counts = self._wrap_lora()
        print(f"LoRA: {counts}", flush=True)
        if t.gradient_checkpointing:
            self.model.gradient_checkpointing_enable(
                gradient_checkpointing_kwargs={"use_reentrant": False}
            )
        targets = self._targets(train)
        pad = self.processor.tokenizer.pad_token_id
        gen = torch.Generator().manual_seed(cfg.seed)
        per_epoch = math.ceil(len(train) / (t.batch_size * t.grad_accum))
        total = t.max_steps or t.epochs * per_epoch
        warmup = max(1, int(t.warmup_ratio * total))
        params = [p for p in self.model.parameters() if p.requires_grad]
        opt = torch.optim.AdamW(params, lr=t.lr, weight_decay=t.weight_decay)
        sched = torch.optim.lr_scheduler.LambdaLR(
            opt, lambda s: min(1.0, (s + 1) / warmup)
            * 0.5 * (1 + math.cos(math.pi * min(1.0, s / max(1, total)))),
        )  # fmt: skip
        log_path = run_dir / "train_log.csv"
        with log_path.open("w", newline="") as fh:
            csv.writer(fh).writerow(["step", "epoch", "train_loss", "val_recall_at_p", "val_ap",
                                     "train_decision_ce", "lr", "seconds"])  # fmt: skip
        val_y = np.array([f.quality_issue for f in val])
        target = cfg.eval.selection_precision_target
        best, best_state, best_step, stale, step = None, None, 0, 0, 0
        select_from = int(t.selection_start_fraction * total)
        losses: list[float] = []
        dec_losses: list[float] = []
        cls_losses: list[torch.Tensor] = []
        started = time.perf_counter()

        def evaluate() -> bool:
            nonlocal best, best_state, best_step, stale
            self.model.eval()
            scores = self.score(val)  # same P(true) as generation, one forward pass
            self.model.train()
            key = selection_key(val_y, scores, target)
            dec_ce = float(torch.stack(dec_losses).mean()) if dec_losses else None
            row = [
                step,
                step / per_epoch,
                float(torch.stack(losses).mean()) if losses else None,
                key[0],
                key[1],
                dec_ce,
                sched.get_last_lr()[0],
                time.perf_counter() - started,
            ]
            with log_path.open("a", newline="") as fh:
                csv.writer(fh).writerow(row)  # fmt: skip
            cls_ce = float(torch.stack(cls_losses).mean()) if cls_losses else float("nan")
            print(f"step {step} loss {row[2]:.4f} decision_ce {dec_ce:.4f} "
                  f"val R@P{target} {key[0]:.3f} AP {key[1]:.3f} ({row[-1]:.0f}s) "
                  f"class_ce {cls_ce:.4f}", flush=True)  # fmt: skip
            losses.clear()
            dec_losses.clear()
            cls_losses.clear()
            if step < select_from and step < total:
                return False  # too early to select; see train.selection_start_fraction
            if best is None or key > best:
                best, best_step, stale = key, step, 0
                best_state = {n: p.detach().cpu().clone() for n, p in self.model.named_parameters()
                              if p.requires_grad}  # fmt: skip
                return False
            stale += 1
            return stale >= t.early_stopping_patience

        self.model.train()
        stop = False
        while not stop:
            order = self._order(train, gen)
            for i in range(0, len(order), t.batch_size):
                idx = order[i : i + t.batch_size]
                chunk = self._examples([train[j] for j in idx], [targets[j] for j in idx])
                batch, labels = collate(chunk, pad)
                batch = {k: v.to(self.device, non_blocking=True) for k, v in batch.items()}
                weights = torch.tensor([e.weight for e in chunk], device=self.device)
                span = answer_span(chunk)
                loss, dec, cls = self._loss(batch, labels.to(self.device), weights, span,
                                            class_mask_tail(chunk, span))  # fmt: skip
                dec_losses.append(dec)  # tensors; synced only at evaluation time
                cls_losses.append(cls)
                (loss / t.grad_accum).backward()
                losses.append(loss.detach())
                if (i // t.batch_size + 1) % t.grad_accum:
                    continue
                torch.nn.utils.clip_grad_norm_(params, t.max_grad_norm)
                opt.step()
                opt.zero_grad(set_to_none=True)
                sched.step()
                step += 1
                if step % t.eval_every_steps == 0 or step >= total:
                    stop = evaluate() or step >= total
                if stop:
                    break
        current = dict(self.model.named_parameters())
        with torch.no_grad():
            for name, value in best_state.items():
                current[name].copy_(value.to(current[name].dtype))
        self.model.eval()
        return TrainingResult(
            artifact_path=run_dir / "adapter",
            best_validation_metrics_path=log_path,
            details={
                "mode": "lora", **counts, "steps": step, "best_step": best_step,
                "selection": {"val_recall_at_precision": best[0], "val_ap": best[1],
                              "precision_target": target},
                "vocabulary": list(self.vocab), "prompt_version": cfg.prompt.version,
                "answer_prefix": cfg.model.answer_prefix, "train_examples": len(train),
            },
        )  # fmt: skip

    @torch.no_grad()
    def score(self, frames: Sequence[FrameRecord]) -> np.ndarray:
        """P(true) for quality_issue after the forced prefix, without generating the answer.

        The final hidden state is captured at the output head and only the true/false rows
        are projected, in fp32. bf16 logits are too coarse at this magnitude: P(true) would
        collapse onto a few values (e.g. exactly 1/(1+e)) and create artificial ties.
        `predict` reuses this score, so checkpoint selection matches the final predictions.
        """
        self._load()
        m, out = self.cfg.model, []
        head = self.model.get_output_embeddings()
        ids = self.true_ids + self.false_ids
        rows = head.weight[ids].float()
        n_true = len(self.true_ids)
        captured: list[torch.Tensor] = []
        hook = head.register_forward_hook(lambda mod, inp, _: captured.append(inp[0][:, -1]))
        try:
            for i in range(0, len(frames), m.batch_size):
                chunk = frames[i : i + m.batch_size]
                inputs = self.processor(
                    text=self._texts(len(chunk)), images=[[self._image(f)] for f in chunk],
                    padding=True, return_tensors="pt",
                ).to(self.device)  # fmt: skip
                captured.clear()
                with torch.autocast(self.device.type, dtype=torch.bfloat16,
                                    enabled=self.device.type == "cuda"):  # fmt: skip
                    self.model(**inputs, use_cache=False, logits_to_keep=1)
                logits = captured[-1].float() @ rows.T  # (batch, len(ids)) in fp32
                log_true = torch.logsumexp(logits[:, :n_true], dim=1)
                log_false = torch.logsumexp(logits[:, n_true:], dim=1)
                out += torch.sigmoid(log_true - log_false).cpu().tolist()
        finally:
            hook.remove()
        return np.array(out)

    @torch.no_grad()
    def predict(self, frames: Sequence[FrameRecord]) -> list[AdapterPrediction]:
        self._load()
        m = self.cfg.model
        out: list[AdapterPrediction] = []
        for i in range(0, len(frames), m.batch_size):
            chunk = frames[i : i + m.batch_size]
            start = time.perf_counter()
            # Score and decision come from score(), the same pass used for checkpoint
            # selection; generation is conditioned on that decision and writes the rest.
            score = self.score(chunk).tolist()
            decisions = [s >= m.binary_threshold for s in score]
            images = [[self._image(f)] for f in chunk]
            inputs = self.processor(
                text=self._texts(len(chunk)), images=images, padding=True, return_tensors="pt"
            ).to(self.device)
            first = BooleanFirstToken(
                self.true_ids, self.false_ids, inputs["input_ids"].shape[1], forced=decisions
            )
            # Same bf16 autocast as score(): trained fp32 modules (projector copy, adapters)
            # would otherwise meet bf16 activations and fail with a dtype mismatch.
            with torch.autocast(self.device.type, dtype=torch.bfloat16,
                                enabled=self.device.type == "cuda"):  # fmt: skip
                gen = self.model.generate(
                    **inputs, max_new_tokens=m.max_new_tokens, do_sample=m.do_sample,
                    logits_processor=LogitsProcessorList([first]), return_dict_in_generate=True,
                )  # fmt: skip
            new_tokens = gen.sequences[:, inputs["input_ids"].shape[1] :]
            texts = self.processor.batch_decode(new_tokens, skip_special_tokens=True)
            ms = 1000 * (time.perf_counter() - start) / len(chunk)
            for f, text, s in zip(chunk, texts, score, strict=True):
                out.append(self._output(f, m.answer_prefix + text, s, ms))
        return out

    def _output(self, f: FrameRecord, text: str, score: float, ms: float) -> AdapterPrediction:
        parsed = parse_output(text, self.tax)
        for r in parsed.repairs:
            self.parse_stats[r] = self.parse_stats.get(r, 0) + 1
        if parsed.failed:
            self.parse_stats["failed"] = self.parse_stats.get("failed", 0) + 1
            body = {"quality_issue": False, "issues": [], "severity": None,
                    "explanation": f"PARSE FAILURE ({parsed.error}): {text[:300]}",
                    "confidence": None}  # fmt: skip
        else:
            body = parsed.output
        prediction = Prediction(
            quality_issue=body["quality_issue"],
            issues=[Issue(**i) for i in body["issues"]],
            severity=body["severity"],
            explanation=body["explanation"],
            confidence=body["confidence"],
            metadata=PredictionMetadata(
                model_version=f"{self.cfg.model.name}@{self.cfg.model.revision}",
                timestamp=datetime.now(UTC).isoformat(),
                game_id=f.game_id,
                frame_id=f.key,
                latency_ms=ms,
            ),
        )
        scores = PredictionScores(
            key=f.key,
            quality_issue=score,
            score_source="first_token_p_true",
            parse_failed=parsed.failed,
        )
        return AdapterPrediction(prediction, scores)

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        lora = hasattr(self.model, "peft_config")
        if lora:
            self.model.save_pretrained(path / "lora")
        (path / "vlm.json").write_text(json.dumps({
            "model_id": self.cfg.model.model_id, "revision": self.cfg.model.revision,
            "vocab": list(self.vocab), "lora": lora, "parse_stats": self.parse_stats,
        }, indent=2))  # fmt: skip

    def load(self, path: Path) -> None:
        state = json.loads((path / "vlm.json").read_text())
        if (state["model_id"], state["revision"]) != (self.cfg.model.model_id,
                                                      self.cfg.model.revision):  # fmt: skip
            raise ValueError("Saved adapter was trained on a different base model/revision")
        self.vocab = tuple(state["vocab"])
        self._load()
        if state["lora"]:
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(self.model, path / "lora").to(self.device)
            self.model.eval()
