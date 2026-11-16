"""Model predictions <-> JSONL files, and the normalized table the metrics module consumes."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from streamsense.data import taxonomy as tx
from streamsense.models.base import AdapterPrediction, FrameRecord
from streamsense.utils.io import write_text


def frames_from_manifest(manifest: pd.DataFrame, root: Path) -> list[FrameRecord]:
    return [
        FrameRecord(
            key=r.key,
            game_id=r.game_id,
            frame_idx=int(r.frame_idx),
            image_path=root / r.image_path,
            quality_issue=bool(r.quality_issue),
            terms=tuple(r.terms),
            severity=None if pd.isna(r.severity) else int(r.severity),
            source=r.source,
            description=r.description,
            image_sha256=r.image_sha256,
        )
        for r in manifest.itertuples()
    ]


def write_predictions(run_dir: Path, split: str, preds: list[AdapterPrediction]) -> Path:
    """predictions/<split>.jsonl holds the output contract; scores/<split>.jsonl the sidecar."""
    out = run_dir / "predictions" / f"{split}.jsonl"
    write_text(out, "".join(json.dumps(asdict(p.output)) + "\n" for p in preds))
    write_text(
        run_dir / "scores" / f"{split}.jsonl",
        "".join(json.dumps(asdict(p.scores)) + "\n" for p in preds),
    )
    return out


def read_predictions(run_dir: Path, split: str) -> dict[str, tuple[dict, dict]]:
    outputs = (run_dir / "predictions" / f"{split}.jsonl").read_text().splitlines()
    scores = (run_dir / "scores" / f"{split}.jsonl").read_text().splitlines()
    result = {}
    for o, s in zip(outputs, scores, strict=True):
        score = json.loads(s)
        result[score["key"]] = (json.loads(o), score)
    return result


def _pred_terms(issues: list[dict[str, Any]], tax: tx.Taxonomy) -> tuple[str, ...]:
    return tuple(tx.normalize_term(i.get("raw_term") or i.get("name") or "", tax) for i in issues)


def _pred_crew(issues: list[dict[str, Any]], tax: tx.Taxonomy) -> tuple[str, ...]:
    """Crew class from the normalized raw term; a bare valid crew name is accepted as-is."""
    out = set()
    for issue in issues:
        term = tx.normalize_term(issue.get("raw_term") or "", tax)
        name = issue.get("name")
        if term in tax.mapping or name not in tax.crew_classes:
            out.add(tx.crew_class(term, tax))
        else:
            out.add(name)
    return tuple(sorted(out))


def build_table(
    manifest: pd.DataFrame,
    preds: dict[str, tuple[dict, dict]],
    tax: tx.Taxonomy,
    vocabulary: tuple[str, ...],
) -> pd.DataFrame:
    """Join truth and predictions. Raw model strings never reach metrics un-normalized."""
    missing = set(manifest["key"]) - set(preds)
    if missing:
        raise ValueError(f"{len(missing)} manifest images have no prediction")
    rows = []
    for r in manifest.itertuples():
        output, scores = preds[r.key]
        issues = output.get("issues") or []
        pred_terms = tx.fold_terms(_pred_terms(issues, tax), vocabulary, tax)
        score = scores.get("quality_issue")
        rows.append({
            "key": r.key,
            "game_id": r.game_id,
            "source": r.source,
            "image_path": r.image_path,
            "description": r.description,
            "y": bool(r.quality_issue),
            "pred": bool(output.get("quality_issue")) and not scores.get("parse_failed"),
            "score": np.nan if score is None else float(score),
            "parse_failed": bool(scores.get("parse_failed")),
            "true_terms": tx.fold_terms(r.terms, vocabulary, tax),
            "pred_terms": pred_terms,
            "true_crew": tuple(r.crew_classes),
            "pred_crew": _pred_crew(issues, tax),
            "true_severity": np.nan if pd.isna(r.severity) else float(r.severity),
            "pred_severity": np.nan if output.get("severity") is None
            else float(output["severity"]),
            "severity_score": np.nan if scores.get("severity") is None
            else float(scores["severity"]),
            "term_scores": scores.get("terms") or {},
            "crew_scores": scores.get("crew_classes") or {},
            "weather_related": bool(r.weather_related),
            "explanation": output.get("explanation", ""),
        })  # fmt: skip
    return pd.DataFrame(rows)
