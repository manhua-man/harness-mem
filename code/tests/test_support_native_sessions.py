from __future__ import annotations

from pathlib import Path

from tests.support.native_sessions import jsonl_bytes, write_jsonl


def test_jsonl_bytes_exposes_exact_newline_and_bom_shape() -> None:
    records = [{"type": "user", "content": "项目"}]

    assert jsonl_bytes(records) == (
        '{"type": "user", "content": "项目"}\n'.encode("utf-8")
    )
    assert jsonl_bytes(records, newline="\r\n", bom=True) == (
        b"\xef\xbb\xbf" + '{"type": "user", "content": "项目"}\r\n'.encode("utf-8")
    )


def test_write_jsonl_can_append_native_session_records(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"

    write_jsonl(path, [{"index": 1}])
    write_jsonl(path, [{"index": 2}], append=True)

    assert path.read_bytes() == b'{"index": 1}\n{"index": 2}\n'
