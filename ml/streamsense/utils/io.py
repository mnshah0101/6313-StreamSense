"""Small, explicit filesystem helpers; no data is uploaded."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    """Hash a file in bounded memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, text: str) -> None:
    """Atomically replace a UTF-8 artifact on its destination filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path: Path, value: Any) -> None:
    """Write strict JSON; NaN and infinity are errors, never silent metrics."""
    write_text(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def load_strict_json(text: str) -> Any:
    """Reject duplicate keys and non-finite JSON numbers instead of losing labels."""

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object key; refusing to overwrite a label")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-finite JSON value is not allowed: {value}")

    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject_constant)
