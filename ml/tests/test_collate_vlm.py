import json
from pathlib import Path

import pytest
import torch

from streamsense.data import taxonomy as tx
from streamsense.models.base import FrameRecord
from streamsense.models.output_parser import parse_output
from streamsense.train.collate_vlm import (
    IGNORE,
    Example,
    collate,
    target_segments,
    tokenize_segments,
)

PREFIX = '{"quality_issue":'


class CharTokenizer:
    """One token per character; enough to test masking without downloading a tokenizer."""

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [ord(c) for c in text]}


@pytest.fixture
def tax(make_cfg):
    return tx.Taxonomy.from_config(make_cfg().taxonomy)


def frame(issue=True, terms=("blur", "fog"), severity=3, description=None):
    return FrameRecord("g/frame_01.jpg", "g", 1, Path("x.jpg"), issue, terms, severity, "user",
                       description)  # fmt: skip


def text_of(segments):
    return "".join(t for t, _ in segments)


def test_target_round_trips_through_parser(tax):
    segs = target_segments(frame(), ("blur", "fog", "other"), tax, True, "<eos>")
    text = PREFIX + text_of(segs).removesuffix("<eos>")
    body = json.loads(text)
    assert body["quality_issue"] and body["severity"] == 3
    assert [i["raw_term"] for i in body["issues"]] == ["blur", "fog"]
    assert body["issues"][1]["weather_related"] and body["issues"][1]["name"] == "weather"
    assert not parse_output(text, tax).failed


def test_rare_terms_fold_to_other_and_template_explanation(tax):
    segs = target_segments(frame(terms=("haze",)), ("blur", "other"), tax, True, "")
    body = json.loads(PREFIX + text_of(segs))
    assert body["issues"][0]["raw_term"] == "other"
    assert body["explanation"] == "Visible defects: other."


def test_description_is_used_as_explanation(tax):
    segs = target_segments(frame(description="Left lens\n smeared"), ("blur",), tax, True, "")
    assert json.loads(PREFIX + text_of(segs))["explanation"] == "Left lens smeared"


def test_negative_target(tax):
    segs = target_segments(frame(False, (), None), ("blur",), tax, True, "")
    body = json.loads(PREFIX + text_of(segs))
    assert body == {"quality_issue": False, "issues": [], "severity": None,
                    "explanation": "No visible quality issue.", "confidence": None,
                    "metadata": {}}  # fmt: skip
    assert all(trainable for _, trainable in segs)


def test_unknown_severity_tokens_are_masked(tax):
    segs = target_segments(frame(severity=None, terms=("blur",)), ("blur",), tax, True, "")
    masked = [t for t, trainable in segs if not trainable]
    assert masked == ["null", "null"]  # issue-level and image-level severity
    ids, mask = tokenize_segments(CharTokenizer(), segs)
    assert len(ids) == len(mask) and mask.count(False) == 8


def test_collate_masks_prompt_and_pads():
    def prompt(n):
        return {
            "input_ids": torch.arange(1, n + 1)[None],
            "attention_mask": torch.ones(1, n, dtype=torch.long),
            "mm_token_type_ids": torch.ones(1, n, dtype=torch.long),
            "pixel_values": torch.ones(n * 2, 3),
            "image_grid_thw": torch.tensor([[1, 2, n]]),
        }

    a = Example(prompt(3), [7, 8], [True, False], 1.0)
    b = Example(prompt(5), [9], [True], 2.0)
    batch, labels = collate([a, b], pad_id=0, left=False)
    assert batch["input_ids"].tolist() == [[1, 2, 3, 7, 8, 0], [1, 2, 3, 4, 5, 9]]
    assert batch["attention_mask"].tolist() == [[1, 1, 1, 1, 1, 0], [1] * 6]
    assert labels.tolist() == [[IGNORE] * 3 + [7, IGNORE, IGNORE], [IGNORE] * 5 + [9]]
    assert batch["mm_token_type_ids"].tolist() == [[1, 1, 1, 0, 0, 0], [1] * 5 + [0]]
    assert batch["pixel_values"].shape == (16, 3) and batch["image_grid_thw"].shape == (2, 3)


def test_left_padding_aligns_answers_at_the_end():
    from streamsense.train.collate_vlm import answer_span

    def prompt(n):
        return {
            "input_ids": torch.arange(1, n + 1)[None],
            "attention_mask": torch.ones(1, n, dtype=torch.long),
            "pixel_values": torch.ones(n, 3),
            "image_grid_thw": torch.tensor([[1, 1, n]]),
        }

    a = Example(prompt(3), [7, 8], [True, True], 1.0)
    b = Example(prompt(5), [9], [True], 1.0)
    batch, labels = collate([a, b], pad_id=0)
    assert batch["input_ids"].tolist() == [[0, 1, 2, 3, 7, 8], [1, 2, 3, 4, 5, 9]]
    assert batch["attention_mask"].tolist() == [[0, 1, 1, 1, 1, 1], [1] * 6]
    span = answer_span([a, b])
    assert span == 3
    # Every trainable label lies within the last span-1 positions used by the loss.
    kept = labels[:, -(span - 1) :]
    assert (labels != IGNORE).sum() == (kept != IGNORE).sum() == 3


def test_decision_token_loss_term():
    from types import SimpleNamespace

    from omegaconf import OmegaConf

    from streamsense.models.vlm import VLMAdapter

    logits = torch.log_softmax(torch.randn(1, 4, 5), -1)

    class Stub:
        def __call__(self, **kwargs):
            return SimpleNamespace(logits=logits[:, -kwargs["logits_to_keep"] :])

    labels = torch.tensor([[IGNORE, IGNORE, 2, 3]])  # position 2 is the true/false token
    ce = torch.nn.functional.cross_entropy(logits[0, 1:3], labels[0, 2:], reduction="none")
    for weight in (0.0, 2.0):
        adapter = VLMAdapter.__new__(VLMAdapter)
        adapter.cfg = OmegaConf.create({"train": {"bf16": False, "decision_loss_weight": weight}})
        adapter.device, adapter.model = torch.device("cpu"), Stub()
        loss, decision, _ = adapter._loss({}, labels, torch.ones(1), span=3)
        assert decision.item() == pytest.approx(ce[0].item(), rel=1e-5)
        assert loss.item() == pytest.approx(ce.mean().item() + weight * ce[0].item(), rel=1e-5)


def test_class_names_are_tagged_and_aligned(tax):
    from streamsense.train.collate_vlm import class_mask_tail, tokenize_segments_with_classes

    segs = target_segments(frame(terms=("blur", "fog")), ("blur", "fog"), tax, True, "")
    ids, mask, classes = tokenize_segments_with_classes(CharTokenizer(), segs)
    tagged = "".join(chr(i) for i, c in zip(ids, classes, strict=True) if c)
    assert tagged == '"blur_lens_smear""weather"'  # the two crew-class names, quotes included
    assert text_of(segs) == text_of(target_segments(frame(terms=("blur", "fog")), ("blur", "fog"),
                                                    tax, True, ""))  # fmt: skip
    short = Example({}, ids[:5], mask[:5], 1.0, [False, True, True, False, False])
    long_ = Example({}, ids, mask, 1.0, classes)
    tail = class_mask_tail([short, long_], span=len(ids) + 1)
    assert tail.shape == (2, len(ids))
    assert tail[0].nonzero().flatten().tolist() == [len(ids) - 4, len(ids) - 3]  # right-aligned
    assert tail[1].tolist() == classes


def test_class_token_loss_term():
    from types import SimpleNamespace

    from omegaconf import OmegaConf

    from streamsense.models.vlm import VLMAdapter

    logits = torch.log_softmax(torch.randn(1, 5, 7), -1)

    class Stub:
        def __call__(self, **kwargs):
            return SimpleNamespace(logits=logits[:, -kwargs["logits_to_keep"] :])

    labels = torch.tensor([[IGNORE, 2, 3, 4, 5]])  # decision at 1; class tokens at 3, 4
    span = 5
    ce = torch.nn.functional.cross_entropy(logits[0, :4], labels[0, 1:], reduction="none")
    cm = torch.tensor([[False, False, True, True]])
    adapter = VLMAdapter.__new__(VLMAdapter)
    adapter.device, adapter.model = torch.device("cpu"), Stub()
    for weight in (0.0, 3.0):
        adapter.cfg = OmegaConf.create(
            {"train": {"bf16": False, "decision_loss_weight": 1.0, "class_loss_weight": weight}}
        )
        loss, _, cls = adapter._loss({}, labels, torch.ones(1), span, cm)
        assert cls.item() == pytest.approx(ce[2:].mean().item(), rel=1e-5)
        expected = ce.mean() + ce[0] + weight * ce[2:].mean()
        assert loss.item() == pytest.approx(expected.item(), rel=1e-5)


def _stub_vlm(lora_overrides):
    from omegaconf import OmegaConf
    from torch import nn

    from streamsense.models.vlm import VLMAdapter

    class Block(nn.Module):
        def __init__(self, names):
            super().__init__()
            for n in names:
                setattr(self, n, nn.Linear(2, 2))

    model = nn.Module()
    model.model = nn.Module()
    model.model.language_model = nn.Module()
    model.model.language_model.layers = nn.ModuleList(
        [Block(["q_proj", "gate_proj"]) for _ in range(4)]
    )
    model.model.visual = nn.Module()
    model.model.visual.blocks = nn.ModuleList([Block(["qkv", "gate_proj"]) for _ in range(2)])
    lora = {
        "target_modules": ["q_proj", "gate_proj"],
        "language_scope": "model.language_model",
        "layers": None,
        "vision_target_modules": [],
        "vision_scope": "model.visual.blocks",
    }
    adapter = VLMAdapter.__new__(VLMAdapter)
    adapter.cfg = OmegaConf.create({"train": {"lora": lora | lora_overrides}})
    adapter.model = model
    return adapter


def test_lora_targets_language_only_by_default():
    names = _stub_vlm({}).lora_targets()
    assert len(names) == 8 and not any("visual" in n for n in names)  # gate_proj in vision skipped


def test_lora_targets_layer_range_and_vision():
    names = _stub_vlm({"layers": [2, 3], "target_modules": ["q_proj"]}).lora_targets()
    assert names == ["model.language_model.layers.2.q_proj", "model.language_model.layers.3.q_proj"]
    names = _stub_vlm(
        {"target_modules": ["q_proj"], "vision_target_modules": ["qkv"]}
    ).lora_targets()
    assert sum("visual" in n for n in names) == 2 and len(names) == 6


def test_lora_targets_fail_loudly_on_typos():
    with pytest.raises(ValueError):
        _stub_vlm({"target_modules": ["q_prj"]}).lora_targets()
    with pytest.raises(ValueError):
        _stub_vlm({"vision_target_modules": ["qkvv"]}).lora_targets()
