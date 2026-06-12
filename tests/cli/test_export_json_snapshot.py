from __future__ import annotations

import json
from pathlib import Path

from harness_mem import cli
from harness_mem.commands.maintenance import cmd_export_json_snapshot
from harness_mem.storage.canonical_store import build_canonical_store
from tests.helpers import run


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _seed(data_dir: Path) -> None:
    _write_json(
        data_dir / "structured" / "memory_entries" / "mem-snap.json",
        {
            "id": "mem-snap",
            "project_name": "demo",
            "category": "decision",
            "content": "snapshot export is explicit",
            "confidence": 0.8,
            "status": "accepted",
            "source": "unit",
            "created_at": "2026-06-12T00:00:00+00:00",
            "updated_at": "2026-06-12T00:00:00+00:00",
            "tags": [],
            "compacted": False,
        },
    )


def test_export_json_snapshot_command_respects_dry_run(
    data_dir: Path,
    tmp_path: Path,
    capsys,
) -> None:
    _seed(data_dir)
    build_canonical_store(data_dir, project_name="demo")
    out_dir = tmp_path / "snapshot"

    assert run(cmd_export_json_snapshot("demo", str(out_dir), apply=False)) == 0
    out = capsys.readouterr().out
    assert "Storage v2 JSON snapshot dry run: demo" in out
    assert "No changes written" in out
    assert not out_dir.exists()

    assert run(cmd_export_json_snapshot("demo", str(out_dir), apply=True)) == 0
    out = capsys.readouterr().out
    assert "Exported Storage v2 JSON snapshot: demo" in out
    assert "Snapshot checksum match: true" in out
    assert (out_dir / "structured" / "memory_entries" / "mem-snap.json").exists()


def test_cli_export_json_snapshot_dispatch(
    data_dir: Path,
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    cli.cmd_use("demo")
    _seed(data_dir)
    build_canonical_store(data_dir, project_name="demo")
    out_dir = tmp_path / "snapshot"

    monkeypatch.setattr(
        "sys.argv",
        [
            "harness-mem",
            "maintenance",
            "export-json-snapshot",
            "-p",
            "demo",
            "--export-dir",
            str(out_dir),
        ],
    )
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "Storage v2 JSON snapshot dry run: demo" in out
    assert not out_dir.exists()
