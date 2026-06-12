from __future__ import annotations

import json
from pathlib import Path

from harness_mem.index_fabric import (
    CURRENT_MANIFEST_NAME,
    build_index_generation,
    ensure_index_current,
    load_current_manifest,
    source_fingerprint,
)


def _write_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def test_index_fabric_commits_manifest_last(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    _write_payload(
        source / "structured" / "memory_entries" / "mem-1.json",
        {
            "id": "mem-1",
            "project_name": "demo",
            "content": "manifest last exact word trigram",
        },
    )

    manifest = build_index_generation(source, index, generation_id="gen-test")

    assert (index / CURRENT_MANIFEST_NAME).exists()
    assert manifest.source_fingerprint == source_fingerprint(source)
    assert {sidecar.kind for sidecar in manifest.sidecars} == {
        "exact",
        "word",
        "trigram",
        "graph",
    }
    for sidecar in manifest.sidecars:
        assert (index / sidecar.path).exists()
        assert sidecar.size_bytes > 0


def test_index_fabric_ignores_interrupted_generation_until_manifest_exists(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    _write_payload(source / "mem.json", {"id": "mem", "content": "first"})
    first = build_index_generation(source, index, generation_id="gen-1")
    interrupted = index / "generations" / "gen-interrupted"
    interrupted.mkdir(parents=True)
    (interrupted / "exact.bin").write_text("half-written", encoding="utf-8")

    loaded = load_current_manifest(index)

    assert loaded is not None
    assert loaded.generation_id == first.generation_id


def test_index_fabric_lazy_rebuilds_on_source_fingerprint_drift(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    _write_payload(source / "mem.json", {"id": "mem", "content": "first"})

    first, rebuilt_first = ensure_index_current(source, index)
    assert rebuilt_first is True
    second, rebuilt_second = ensure_index_current(source, index)
    assert rebuilt_second is False
    assert second.generation_id == first.generation_id

    _write_payload(source / "mem-2.json", {"id": "mem-2", "content": "second"})
    third, rebuilt_third = ensure_index_current(source, index)
    assert rebuilt_third is True
    assert third.generation_id != first.generation_id
