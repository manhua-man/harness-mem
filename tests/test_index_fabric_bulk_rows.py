"""Index fabric must compute bulk rows once per publish generation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from harness_mem.index_fabric import manifest as manifest_module


def test_publish_generation_calls_bulk_rows_once(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "a.json").write_text(
        json.dumps({"id": "entity-a", "content": "alpha token"}),
        encoding="utf-8",
    )

    calls: list[int] = []

    def counting_bulk_rows(payloads):
        calls.append(len(payloads))
        return manifest_module.build_bulk_index_rows(
            manifest_module._normalized_payloads(payloads)
        )

    index_dir = tmp_path / "index"
    with patch.object(manifest_module, "_bulk_rows", side_effect=counting_bulk_rows):
        manifest_module.build_index_generation(source_dir, index_dir)

    assert calls == [1]