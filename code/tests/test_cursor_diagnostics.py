"""Developer CLI tests with explicit synthetic databases only."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "tools/harness-mem-debug/scripts"


def run_cli(*args):
    return subprocess.run([sys.executable, str(SCRIPTS / "debug.py"), "cursor-schema", *args],
                          capture_output=True, text=True, timeout=15)


def test_cursor_schema_explicit_readonly_no_values(tmp_path):
    database = tmp_path / "fixture.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO cursorDiskKV VALUES ('composerData:fixture', 'SECRET_VALUE')")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = run_cli("--database", str(database))
    assert result.returncode == 0, result.stderr
    assert "SECRET_VALUE" not in result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["tables"]["cursorDiskKV"]["key_prefixes"] == {"composerData:": 1}
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize("kind", ["missing", "corrupt", "locked"])
def test_cursor_schema_failure_exit(tmp_path, kind):
    database = tmp_path / "fixture.sqlite"
    db = None
    if kind == "corrupt":
        database.write_bytes(b"broken synthetic db")
    elif kind == "locked":
        db = sqlite3.connect(database)
        db.execute("CREATE TABLE fixture(id)")
        db.commit()
        db.execute("BEGIN EXCLUSIVE")
    try:
        result = run_cli("--database", str(database))
        assert result.returncode == 3
        assert json.loads(result.stdout)["status"] == "unreadable"
        if kind == "missing":
            assert not database.exists()
    finally:
        if db is not None:
            db.close()


def test_cursor_schema_requires_explicit_path():
    result = run_cli()
    assert result.returncode == 2
    assert "--database" in result.stderr


def test_synthetic_prefix_benchmark_equivalence_and_plan():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "cursor_prefix_benchmark.py"), "--rows", "2000", "--repeats", "2"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["equivalent"] and report["synthetic_only"]
    assert report["rows"] == 2000 and report["matched_rows"] == 2
    assert any("SEARCH" in plan for plan in report["query_plans"]["range"])
    assert any("SCAN" in plan for plan in report["query_plans"]["scan"])
    assert len(report["milliseconds"]["range"]["samples"]) == 2
