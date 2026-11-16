"""Reject private data in the Git index, including blobs disguised by a new extension."""

import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from streamsense.config import PrivacyConfig


def path_violation(name: str, policy: PrivacyConfig, labels_file: str | None) -> str | None:
    """Return a reason for a private path without reading its contents."""
    path = PurePosixPath(name.lower())
    protected = {n.lower() for n in policy.protected_dirs}
    # Root-anchored like .gitignore (/data/, /outputs/, ...): source packages such as
    # streamsense/data/ and conf/data/ are code, not client data.
    if path.parts and path.parts[0] in protected:
        return "private artifact directory"
    files = {n.lower() for n in policy.protected_files}
    if path.as_posix() in files or path.name in files:
        return "private report or labels filename"
    if labels_file and path.name == PurePosixPath(labels_file.lower()).name:
        return "configured labels filename"
    if path.suffix in {ext.lower() for ext in policy.blocked_extensions}:
        return "image, archive, dataset, or checkpoint extension"
    return None


def _looks_like_labels(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(
        isinstance(row, dict) and "decision" in row and ("term" in row or "source" in row)
        for row in value.values()
    )


def _notebook_with_outputs(value: Any) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("cells"), list):
        return False
    return any(
        isinstance(c, dict) and (c.get("outputs") or c.get("execution_count"))
        for c in value["cells"]
    )


def content_violation(blob: bytes, *, scan_json: bool) -> str | None:
    """Check common binary signatures and recognizable label objects."""
    signatures = (
        b"\xff\xd8\xff",
        b"\x89PNG\r\n\x1a\n",
        b"GIF87a",
        b"GIF89a",
        b"II*\x00",
        b"MM\x00*",
        b"PK\x03\x04",
        b"PK\x05\x06",
        b"\x1f\x8b",
        b"7z\xbc\xaf\x27\x1c",
        b"Rar!\x1a\x07",
    )
    if blob.startswith(signatures):
        return "image or archive file signature"
    if blob[:4] == b"RIFF" and blob[8:12] in {b"WEBP", b"AVI "}:
        return "image or video file signature"
    if blob[257:262] == b"ustar":
        return "tar archive file signature"
    if scan_json:
        try:
            value = json.loads(blob.decode("utf-8-sig"))
        except (ValueError, UnicodeError):
            return None
        if _looks_like_labels(value):
            return "label JSON content (renaming the file does not make it public)"
        if _notebook_with_outputs(value):
            return "notebook with outputs (client-derived results); strip outputs first"
    return None


def staged_violations(
    root: Path, policy: PrivacyConfig, labels_file: str | None
) -> list[tuple[str, str]]:
    """Inspect Git-index blobs, never a possibly different working-tree version."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    violations = []
    for raw in result.stdout.split(b"\x00"):
        if not raw:
            continue
        name = raw.decode("utf-8", errors="surrogateescape")
        reason = path_violation(name, policy, labels_file)
        if reason is None:
            blob = subprocess.run(
                ["git", "show", f":{name}"], cwd=root, check=True, capture_output=True
            ).stdout
            reason = content_violation(blob, scan_json=policy.scan_json_contents)
        if reason:
            violations.append((name, reason))
    return violations
