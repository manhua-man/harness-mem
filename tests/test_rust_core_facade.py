from __future__ import annotations

import json
from pathlib import Path

from harness_mem.rust_core import (
    build_bulk_index_rows,
    error_to_hm_code,
    rank_candidates,
    reciprocal_rank_fusion,
    rust_core_status,
    scan_jsonl,
)


def test_rust_core_status_uses_python_fallback_when_wheel_missing() -> None:
    status = rust_core_status()

    assert status.api_version == "v4.0.2"
    assert status.mode in {"rust", "python_fallback"}
    if status.mode == "python_fallback":
        assert status.available is False
        assert status.fallback_reason


def test_tolerant_jsonl_scanner_keeps_good_records_and_reports_errors() -> None:
    result = scan_jsonl(
        '{"type":"user","content":"hello"}\n'
        '\n'
        'not-json\n'
        '[1, 2]\n'
        '{"type":"assistant","content":"world"}\n'
    )

    assert [row["type"] for row in result.records] == ["user", "assistant"]
    assert [error["code"] for error in result.errors] == ["HM-410", "HM-411"]
    assert result.to_dict()["record_count"] == 2


def test_facade_prefers_native_module_when_available(monkeypatch) -> None:
    class NativeStub:
        @staticmethod
        def api_version() -> str:
            return "v4.0.2"

        @staticmethod
        def scan_jsonl(text: str) -> str:
            return json.dumps(
                {
                    "records": [{"type": "native"}],
                    "errors": [{"line": 2, "code": "HM-410", "message": "bad"}],
                }
            )

        @staticmethod
        def build_bulk_index_rows(payloads_json: str) -> str:
            payloads = json.loads(payloads_json)
            return json.dumps(
                [
                    {
                        "id": payloads[0]["id"],
                        "tokens": ["native"],
                        "exact_terms": ["native"],
                        "trigrams": ["nat"],
                        "metadata": {
                            "project_id": "demo",
                            "truth_status": "accepted",
                            "confidence": 0.9,
                        },
                    }
                ]
            )

        @staticmethod
        def reciprocal_rank_fusion(lists_json: str, k: float) -> str:
            assert k == 60.0
            assert json.loads(lists_json) == [["a", "b"], ["b", "c"]]
            return json.dumps([["b", 2.0], ["a", 1.0]])

        @staticmethod
        def rank_candidates(rows_json: str, query: str, source_diversity_penalty: float) -> str:
            assert query == "storage v2"
            assert source_diversity_penalty == 0.05
            rows = json.loads(rows_json)
            return json.dumps([{**rows[0], "id": rows[0]["id"], "score": 9.0}])

        @staticmethod
        def tokens(text: str) -> list[str]:
            return ["native", text.lower()]

    import importlib

    original_import_module = importlib.import_module

    def fake_import_module(name: str):
        if name == "harness_mem_core_rs":
            return NativeStub
        return original_import_module(name)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    status = rust_core_status()
    assert status.mode == "rust"
    assert status.available is True
    assert scan_jsonl('{"id":"one"}').records == [{"type": "native"}]
    assert build_bulk_index_rows([{"id": "mem-1"}])[0]["tokens"] == ["native"]
    assert list(reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60)) == ["b", "a"]
    assert rank_candidates(
        [{"id": "a", "tokens": ["storage"], "confidence": 0.8, "truth_status": "accepted"}],
        query="storage v2",
    )[0]["score"] == 9.0


def test_bulk_index_builder_extracts_tokens_metadata_and_trigrams() -> None:
    rows = build_bulk_index_rows(
        [
            {
                "id": "mem-1",
                "project_name": "demo",
                "content": "Storage v2 builds exact trigram indexes",
                "status": "accepted",
                "confidence": 0.9,
            }
        ]
    )

    assert rows[0]["id"] == "mem-1"
    assert "storage" in rows[0]["tokens"]
    assert "exact" in rows[0]["exact_terms"]
    assert rows[0]["metadata"]["project_id"] == "demo"
    assert rows[0]["trigrams"]


def test_ranking_primitives_are_deterministic() -> None:
    scores = reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60)
    assert list(scores) == ["b", "a", "c"]

    ranked = rank_candidates(
        [
            {
                "id": "a",
                "tokens": ["storage", "v2"],
                "confidence": 0.8,
                "truth_status": "accepted",
                "project_id": "demo",
            },
            {
                "id": "b",
                "tokens": ["storage"],
                "confidence": 0.8,
                "truth_status": "pending",
                "project_id": "demo",
            },
        ],
        query="storage v2",
    )
    assert [row["id"] for row in ranked] == ["a", "b"]
    assert ranked[0]["score"] > ranked[1]["score"]


def test_error_mapping_uses_stable_hm_codes() -> None:
    payload = error_to_hm_code(ValueError("bad row"))
    assert payload == {"code": "HM-411", "message": "bad row"}


def test_rust_crate_shape_is_present() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "Cargo.toml").exists()
    assert (root / "crates" / "harness_mem_core_rs" / "Cargo.toml").exists()
    assert (root / "crates" / "harness_mem_core_rs" / "src" / "lib.rs").exists()
