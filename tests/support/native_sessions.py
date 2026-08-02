"""Small lossless native-session writers shared by adapter unit tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Write deterministic UTF-8 JSONL without borrowing production fixtures."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
        + "\n",
        encoding="utf-8",
    )
