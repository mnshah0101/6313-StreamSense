"""Model text -> output-contract dict, with bounded repairs and explicit failure reasons.

Pure functions. Repairs are recorded so parse quality can be reported, and anything that
cannot be repaired is a parse failure (counted as "no issue" by the metrics module).
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from streamsense.data import taxonomy as tx


@dataclass
class ParseResult:
    output: dict[str, Any] | None
    repairs: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.output is None


def extract_json_object(text: str) -> tuple[str | None, list[str]]:
    """First balanced {...} block, ignoring braces inside strings; strips code fences."""
    repairs = []
    if "```" in text:
        text = re.sub(r"```(?:json)?", "", text)
        repairs.append("stripped_code_fence")
    start = text.find("{")
    if start < 0:
        return None, repairs
    if text[:start].strip():
        repairs.append("dropped_leading_text")
    depth, in_str, escape = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            escape = ch == "\\" and not escape
            if ch == '"' and not escape:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                if text[i + 1 :].strip():
                    repairs.append("dropped_trailing_text")
                return text[start : i + 1], repairs
    return None, [*repairs, "unbalanced_braces"]


def _loads(block: str) -> tuple[Any, list[str]]:
    try:
        return json.loads(block), []
    except json.JSONDecodeError:
        pass
    fixed = re.sub(r",\s*([}\]])", r"\1", block)
    fixed = re.sub(r"\bTrue\b", "true", re.sub(r"\bFalse\b", "false", fixed))
    fixed = re.sub(r"\bNone\b", "null", fixed)
    return json.loads(fixed), ["json_syntax_fixed"]


def _bool(value: Any, name: str, repairs: list[str]) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        repairs.append(f"{name}_string_bool")
        return value.strip().lower() == "true"
    raise ValueError(f"{name} must be a boolean")


def _severity(value: Any, name: str, repairs: list[str]) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(r"\d+(\.\d+)?", value):
            raise ValueError(f"{name} is not numeric")
        value = float(value)
        repairs.append(f"{name}_string_number")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be 1-5 or null")
    if value != int(value):
        repairs.append(f"{name}_rounded")
    value = int(round(value))
    if not 1 <= value <= 5:
        raise ValueError(f"{name} out of range")
    return value


def parse_output(text: str, tax: tx.Taxonomy) -> ParseResult:
    """Parse and validate one model response against the output contract."""
    block, repairs = extract_json_object(text)
    if block is None:
        return ParseResult(None, repairs, "no_json_object")
    try:
        raw, fixes = _loads(block)
    except json.JSONDecodeError as exc:
        return ParseResult(None, repairs, f"invalid_json: {exc.msg}")
    repairs += fixes
    if not isinstance(raw, dict):
        return ParseResult(None, repairs, "not_an_object")
    try:
        issue = _bool(raw.get("quality_issue"), "quality_issue", repairs)
        severity = _severity(raw.get("severity"), "severity", repairs)
        issues = []
        items = raw.get("issues") or []
        if not isinstance(items, list):
            raise ValueError("issues must be a list")
        for item in items:
            if isinstance(item, str):
                item = {"raw_term": item}
                repairs.append("issue_string")
            if not isinstance(item, dict):
                raise ValueError("issue must be an object")
            term = tx.normalize_term(str(item.get("raw_term") or item.get("name") or ""), tax)
            if not term:
                repairs.append("dropped_empty_issue")
                continue
            issues.append({
                "name": tx.crew_class(term, tax),
                "raw_term": term,
                "severity": _severity(item.get("severity", severity), "issue_severity", repairs),
                "weather_related": tx.weather_related((term,), tax),
            })  # fmt: skip
        confidence = raw.get("confidence")
        if confidence is not None and (
            isinstance(confidence, bool)
            or not isinstance(confidence, int | float)
            or not 0 <= confidence <= 1
        ):
            confidence = None
            repairs.append("confidence_invalid_dropped")
    except ValueError as exc:
        return ParseResult(None, repairs, f"schema: {exc}")
    if not issue and (issues or severity is not None):
        repairs.append("negative_cleared_issues")
        issues, severity = [], None
    if issue and severity is None and issues:
        known = [i["severity"] for i in issues if i["severity"] is not None]
        severity = max(known) if known else None
    explanation = raw.get("explanation")
    return ParseResult(
        {
            "quality_issue": issue,
            "issues": issues,
            "severity": severity,
            "explanation": explanation if isinstance(explanation, str) else "",
            "confidence": None if confidence is None else float(confidence),
        },
        repairs,
    )
