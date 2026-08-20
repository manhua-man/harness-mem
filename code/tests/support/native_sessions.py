"""Small lossless native-session writers shared by adapter unit tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def jsonl_bytes(
    records: Iterable[dict[str, Any]],
    *,
    newline: str = "\n",
    bom: bool = False,
) -> bytes:
    """Render deterministic native JSONL with explicit byte-shape controls."""

    text = (
        newline.join(json.dumps(record, ensure_ascii=False) for record in records)
        + newline
    )
    prefix = b"\xef\xbb\xbf" if bom else b""
    return prefix + text.encode("utf-8")


def write_jsonl(
    path: Path,
    records: Iterable[dict[str, Any]],
    *,
    newline: str = "\n",
    bom: bool = False,
    append: bool = False,
) -> None:
    """Write deterministic JSONL without borrowing production fixtures."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = jsonl_bytes(records, newline=newline, bom=bom)
    mode = "ab" if append else "wb"
    with path.open(mode) as handle:
        handle.write(payload)
