"""SFT targets and batches for VLM LoRA: loss on answer tokens only.

The prompt (system + image + user text + forced answer prefix) is identical to inference and
fully masked. The target continues after the prefix. Unknown severities are written as `null`
but those tokens are masked, so the model is never taught a severity value it wasn't given.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import torch

from streamsense.data import taxonomy as tx
from streamsense.models.base import FrameRecord

IGNORE = -100
IMAGE_KEYS = {"pixel_values", "image_grid_thw", "pixel_values_videos", "video_grid_thw"}
Segment = tuple[str, bool]  # (text, contributes to loss)


class ClassName(str):
    """Marks a segment holding a crew-class name, so its tokens can get an extra loss term
    (`train.class_loss_weight`). Behaves exactly like the plain string otherwise."""


def _json_str(value: str) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def explanation_for(frame: FrameRecord, terms: Sequence[str], use_description: bool) -> str:
    if use_description and frame.description and frame.description.strip():
        return " ".join(frame.description.split())
    if not frame.quality_issue:
        return "No visible quality issue."
    return f"Visible defects: {', '.join(terms)}."


def target_segments(
    frame: FrameRecord,
    vocabulary: Sequence[str],
    tax: tx.Taxonomy,
    use_description: bool,
    eos: str,
) -> list[Segment]:
    """Answer text after the forced '{"quality_issue":' prefix, split into loss segments."""
    terms = tx.fold_terms(frame.terms, vocabulary, tax) if frame.quality_issue else ()
    sev_known = frame.severity is not None
    sev = str(frame.severity) if sev_known else "null"
    segs: list[Segment] = [(f' {"true" if frame.quality_issue else "false"}, "issues": [', True)]
    for i, term in enumerate(terms):
        weather = "true" if tx.weather_related((term,), tax) else "false"
        segs += [
            (("" if i == 0 else ", ") + '{"name": ', True),
            (ClassName(_json_str(tx.crew_class(term, tax))), True),
            (f', "raw_term": {_json_str(term)}, "severity": ', True),
            (sev, sev_known),
            (f', "weather_related": {weather}}}', True),
        ]  # fmt: skip
    segs.append(('], "severity": ', True))
    segs.append((sev if frame.quality_issue else "null", sev_known or not frame.quality_issue))
    explanation = explanation_for(frame, terms, use_description)
    segs.append((f', "explanation": {_json_str(explanation)}, "confidence": null, '
                 '"metadata": {}}', True))  # fmt: skip
    segs.append((eos, True))
    return segs


def tokenize_segments(tokenizer, segments: Sequence[Segment]) -> tuple[list[int], list[bool]]:
    ids, mask, _ = tokenize_segments_with_classes(tokenizer, segments)
    return ids, mask


def tokenize_segments_with_classes(
    tokenizer, segments: Sequence[Segment]
) -> tuple[list[int], list[bool], list[bool]]:
    """Token ids, loss mask, and which tokens belong to crew-class names (see ClassName)."""
    ids: list[int] = []
    mask: list[bool] = []
    classes: list[bool] = []
    for text, trainable in segments:
        piece = tokenizer(text, add_special_tokens=False)["input_ids"]
        ids += piece
        mask += [trainable] * len(piece)
        classes += [isinstance(text, ClassName)] * len(piece)
    return ids, mask, classes


def answer_span(examples: Sequence["Example"]) -> int:
    """Logit positions needed for the loss with left padding: longest target plus one."""
    return max(len(ex.target_ids) for ex in examples) + 1


@dataclass
class Example:
    prompt: dict[str, torch.Tensor]  # processor output for one prompt+image (batch dim 1)
    target_ids: list[int]
    target_mask: list[bool]
    weight: float
    class_mask: list[bool] | None = None  # tokens of crew-class names (same length as target)


def class_mask_tail(examples: Sequence[Example], span: int) -> torch.Tensor:
    """Bool (batch, span-1) marking class-name tokens, aligned with the loss slice
    `labels[:, -(span-1):]` of a left-padded batch (every answer ends at the last position)."""
    out = torch.zeros((len(examples), span - 1), dtype=torch.bool)
    for i, ex in enumerate(examples):
        if not ex.class_mask:
            continue
        offset = span - 1 - len(ex.target_ids)
        for j, is_class in enumerate(ex.class_mask):
            if is_class:
                out[i, offset + j] = True
    return out


def collate(
    examples: Sequence[Example], pad_id: int, left: bool = True
) -> tuple[dict[str, torch.Tensor], torch.Tensor]:
    """Pad prompt+target; labels are -100 except trainable target tokens.

    Left padding (default) makes every answer end at the last position, so the loss only
    needs logits for the final `answer_span(examples)` positions. Sequence-shaped processor
    outputs are padded; image tensors are concatenated.
    """
    seqs, labels, extras = [], [], []
    for ex in examples:
        ids = ex.prompt["input_ids"][0]
        target = torch.tensor(ex.target_ids, dtype=ids.dtype)
        seqs.append(torch.cat([ids, target]))
        lab = torch.where(torch.tensor(ex.target_mask), target, torch.tensor(IGNORE))
        labels.append(torch.cat([torch.full_like(ids, IGNORE), lab]))
        extras.append(len(ids))
    width = max(len(s) for s in seqs)
    batch: dict[str, torch.Tensor] = {
        "input_ids": torch.full((len(seqs), width), pad_id, dtype=seqs[0].dtype),
        "attention_mask": torch.zeros((len(seqs), width), dtype=torch.long),
    }
    label_t = torch.full((len(seqs), width), IGNORE, dtype=torch.long)
    seq_keys = [
        k for k in examples[0].prompt
        if k not in batch and k not in IMAGE_KEYS
        and all(ex.prompt[k].shape == ex.prompt["input_ids"].shape for ex in examples)
    ]  # fmt: skip
    for k in seq_keys:
        batch[k] = torch.zeros((len(seqs), width), dtype=examples[0].prompt[k].dtype)
    for i, (ex, s, lab, n_prompt) in enumerate(zip(examples, seqs, labels, extras, strict=True)):
        start = width - len(s) if left else 0
        batch["input_ids"][i, start : start + len(s)] = s
        batch["attention_mask"][i, start : start + len(s)] = 1
        label_t[i, start : start + len(lab)] = lab
        for k in seq_keys:  # e.g. mm_token_type_ids: prompt values, zeros for text target
            batch[k][i, start : start + n_prompt] = ex.prompt[k][0]
    for k in examples[0].prompt:
        if k not in batch and k not in seq_keys:
            batch[k] = torch.cat([ex.prompt[k] for ex in examples], dim=0)
    return batch, label_t
