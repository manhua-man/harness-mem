from __future__ import annotations

from pathlib import Path

import harness_mem.mcp.distill_projection as distill_projection
from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.mcp.distill_projection import (
    DISTILL_INCREMENTAL_PROJECTION,
    build_append_aware_distill_projection,
    build_distill_compact_outline,
    build_distill_semantic_outline,
    render_distill_exchange_windows,
)
from harness_mem.storage.transcript_store import TranscriptStore
from harness_mem.transcript_chunking import (
    chunk_transcript_text,
    sha256_bytes,
    sha256_text,
    transcript_bytes_revision,
    transcript_source_id,
)


def _long_session(exchange_count: int = 60) -> str:
    parts = ["# Session\n"]
    for index in range(1, exchange_count + 1):
        user = (
            f"routine request {index} "
            + "inspect implementation details and keep the result concise " * 6
        )
        outcome = (
            f"routine outcome {index} "
            + "verified the requested path and recorded the result " * 7
        )
        if index == 19:
            user = (
                "Storage migration v0.8.24 checksum conflict requires rollback. "
                "PRIVATE-PROOF-ALPHA must remain available for raw verification."
            )
            outcome = (
                "Migration failed before activation; canonical data was preserved "
                "and rollback remains required. PRIVATE-PROOF-OMEGA"
            )
        if index == exchange_count:
            user = "Finish the iteration without hiding unfinished work."
            outcome = "Blocked by the remaining security review; work is unfinished."
        parts.extend(
            [
                f"## Turn {index * 3 - 2} (user-{index})\n\nUser: {user}\n\n",
                f"## Turn {index * 3 - 1} (assistant-{index})\n\nAssistant: progress {index}\n\n",
                f"## Turn {index * 3} (assistant-final-{index})\n\nAssistant: {outcome}\n\n",
                'Tool: wait -> {"cell_id":"1"}\n\n',
                'Tool: pytest -> {"status":"passed"}\n\n',
            ]
        )
    return "".join(parts)


def test_compact_outline_covers_every_exchange_within_soft_budget() -> None:
    source = _long_session()
    compact, summary = build_distill_compact_outline(source, budget_tokens=3000)
    full, _full_summary = build_distill_semantic_outline(source)

    assert summary["projection"] == "exchange-outline-v2"
    assert summary["budget_state"] == "within_budget"
    assert summary["output_tokens"] <= 3000
    assert summary["exchange_count"] == 60
    assert summary["zero_candidate_challenge_version"] == "v1"
    assert summary["zero_candidate_required_exchange_indexes"][-1] == 60
    assert 19 in summary["zero_candidate_required_exchange_indexes"]
    assert len(summary["zero_candidate_required_exchange_indexes"]) <= 8
    assert "version_or_migration" in summary[
        "zero_candidate_required_exchange_reasons"
    ]["19"]
    assert compact.count("## E") == 60
    assert "s=VMPFC" in compact
    assert "PRIVATE-PROOF-ALPHA" in compact
    assert "PRIVATE-PROOF-OMEGA" in compact
    assert "s=PU" in compact
    assert "work is unfinished" in compact
    assert len(compact) < len(full)


def test_semantic_window_restores_complete_selected_exchange() -> None:
    source = _long_session()
    windows = render_distill_exchange_windows(source, [19])

    assert len(windows) == 1
    assert windows[0]["exchange_index"] == 19
    assert "PRIVATE-PROOF-ALPHA" in windows[0]["content"]
    assert "PRIVATE-PROOF-OMEGA" in windows[0]["content"]
    assert "migration_storage" in windows[0]["risk_flags"]
    assert "version_or_migration" in windows[0]["memory_signals"]


def test_compact_outline_preserves_evidence_anchors_with_fallback_counter(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        distill_projection,
        "_count_tokens",
        lambda value: len(value) // 4,
    )

    compact, summary = build_distill_compact_outline(
        _long_session(),
        budget_tokens=3000,
    )

    assert summary["budget_state"] == "within_budget"
    assert "PRIVATE-PROOF-ALPHA" in compact
    assert "PRIVATE-PROOF-OMEGA" in compact


def test_compact_outline_expands_instead_of_silently_dropping_coverage() -> None:
    source = _long_session(exchange_count=120)
    compact, summary = build_distill_compact_outline(source, budget_tokens=256)

    assert summary["budget_state"] == "expanded_for_manifest"
    assert summary["budget_reason"]
    assert compact.count("## E") == 120


def test_compact_outline_keeps_dense_risk_session_within_daily_budget() -> None:
    parts = ["# Dense risk session\n"]
    for index in range(1, 48):
        parts.append(
            f"User: 检查版本发布、存储迁移、隐私删除、失败冲突和剩余工作 {index}。\n\n"
            "Assistant: 已验证 checksum、rollback、security、timeout、stale 和 TODO；"
            f"需要按证据继续处理第 {index} 项。" * 8
            + "\n\n"
        )

    compact, summary = build_distill_compact_outline(
        "".join(parts),
        budget_tokens=3000,
    )

    assert summary["exchange_count"] == 47
    assert summary["risk_exchange_count"] == 47
    assert summary["budget_state"] == "within_budget"
    assert summary["output_tokens"] <= 3000
    assert compact.count("## E") == 47


def test_append_aware_projection_parses_only_verified_parser_tail(
    monkeypatch,
) -> None:
    base_parser = (
        "# Session\n\nUser: inspect the first path\n\n"
        "Assistant: first path verified\n\n"
    )
    parser_tail = (
        "User: decide the reusable policy\n\n"
        "Assistant: default to the verified path\n\n"
    )
    base_source = b'{"event":"first"}\n'
    current_source = base_source + b'{"event":"second"}\n'
    base_revision = transcript_bytes_revision(base_source)
    current_revision = transcript_bytes_revision(current_source)

    _base_content, _base_summary, base_lineage = (
        build_append_aware_distill_projection(
            base_parser,
            source_revision=base_revision,
            source_bytes=base_source,
        )
    )
    original_parse = distill_projection._parse_exchanges
    parsed_values: list[str] = []

    def recording_parse(value: str):
        parsed_values.append(value)
        return original_parse(value)

    monkeypatch.setattr(distill_projection, "_parse_exchanges", recording_parse)
    content, summary, lineage = build_append_aware_distill_projection(
        base_parser + parser_tail,
        source_revision=current_revision,
        source_bytes=current_source,
        covered_sequence_count=2,
        previous_projection=base_lineage,
        previous_source_bytes=base_source,
    )
    expected, expected_summary = build_distill_compact_outline(
        base_parser + parser_tail
    )

    assert parsed_values[0] == parser_tail
    assert content == expected
    assert summary["exchange_count"] == expected_summary["exchange_count"] == 2
    assert summary["projection_build_mode"] == "append"
    assert lineage["base_revision"] == base_revision
    assert lineage["covered_boundary"] == {
        "raw_bytes": len(current_source),
        "parser_chars": len(base_parser + parser_tail),
        "sequence_count": 2,
    }
    assert lineage["verified_prefix_sha256"] == sha256_bytes(base_source)
    assert lineage["previous_projection_sha256"] == base_lineage[
        "projection_sha256"
    ]
    assert lineage["appended_raw_bytes"] == len(current_source) - len(base_source)
    assert lineage["appended_parser_chars"] == len(parser_tail)


def test_semantic_chunks_keep_complete_tool_exchange_together() -> None:
    first = "## E1 [-]\nU: inspect\nA: " + ("a" * 17_000) + "\nT: pytest\n"
    second = "## E2 [-]\nU: verify\nA: " + ("b" * 17_000) + "\nT: git status\n"
    value = "# semantic manifest\n" + first + second

    chunks = distill_projection.split_distill_semantic_content(value)

    assert "".join(chunk["content"] for chunk in chunks) == value
    assert len(chunks) == 2
    assert chunks[0]["logical_unit_ids"] == ["semantic-header", "exchange-1"]
    assert chunks[1]["logical_unit_ids"] == ["exchange-2"]
    assert all(chunk["ends_with_continuation"] is False for chunk in chunks)


def test_oversized_semantic_exchange_reports_continuation() -> None:
    value = "## E1 [-]\nU: inspect\nA: " + ("x" * 70_000) + "\nT: pytest\n"

    chunks = distill_projection.split_distill_semantic_content(value)

    assert "".join(chunk["content"] for chunk in chunks) == value
    assert len(chunks) == 3
    assert chunks[0]["ends_with_continuation"] is True
    assert chunks[1]["starts_with_continuation"] is True
    assert chunks[1]["ends_with_continuation"] is True
    assert chunks[-1]["starts_with_continuation"] is True
    assert chunks[-1]["ends_with_continuation"] is False


def test_append_aware_projection_falls_back_when_native_prefix_changes() -> None:
    base_parser = "User: choose A\n\nAssistant: A selected\n"
    base_source = b"native-a\n"
    _content, _summary, base_lineage = build_append_aware_distill_projection(
        base_parser,
        source_revision=transcript_bytes_revision(base_source),
        source_bytes=base_source,
    )
    rewritten_parser = "User: choose B\n\nAssistant: B selected\n"
    rewritten_source = b"native-b\n"

    content, summary, lineage = build_append_aware_distill_projection(
        rewritten_parser,
        source_revision=transcript_bytes_revision(rewritten_source),
        source_bytes=rewritten_source,
        previous_projection=base_lineage,
        previous_source_bytes=base_source,
    )
    expected, _expected_summary = build_distill_compact_outline(rewritten_parser)

    assert content == expected
    assert summary["projection_build_mode"] == "full"
    assert lineage["base_revision"] is None
    assert lineage["fallback_reason"] == "source_prefix_mismatch"
    assert lineage["verified_prefix_sha256"] is None


def test_append_aware_projection_rejects_unproven_current_revision() -> None:
    source = b"native source"

    try:
        build_append_aware_distill_projection(
            "User: hello",
            source_revision="sha256:not-the-source",
            source_bytes=source,
        )
    except ValueError as exc:
        assert "exact native source bytes" in str(exc)
    else:
        raise AssertionError("unproven source revision was accepted")


def _projection_snapshot(value: str) -> tuple[TranscriptSource, list]:
    source_id = transcript_source_id(
        client="codex",
        project_name="projection-demo",
        session_id="session-1",
    )
    native = value.encode("utf-8")
    revision = transcript_bytes_revision(native)
    source = TranscriptSource(
        id=source_id,
        project_name="projection-demo",
        project_root="C:/work/projection-demo",
        client="codex",
        session_id="session-1",
        source_kind="file",
        source_uri="file:///C:/sessions/session-1.jsonl",
        source_revision=revision,
        raw_sha256=sha256_bytes(native),
        normalized_sha256=sha256_text(value),
        raw_size_bytes=len(native),
        normalized_size_bytes=len(native),
    )
    chunks = chunk_transcript_text(
        value,
        source_id=source_id,
        project_name=source.project_name,
        client=source.client,
        session_id=source.session_id,
        source_revision=revision,
    )
    return source, chunks


def test_projection_lineage_cache_is_revision_scoped_and_disposable(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path)
    first_value = "User: first\n\nAssistant: done\n"
    second_value = first_value + "User: second\n\nAssistant: done again\n"
    first_source, first_chunks = _projection_snapshot(first_value)
    second_source, second_chunks = _projection_snapshot(second_value)
    store.save_snapshot(first_source, first_chunks)
    _content, _summary, first_record = build_append_aware_distill_projection(
        first_value,
        source_revision=first_source.source_revision,
        source_bytes=first_value.encode("utf-8"),
    )
    first_record["source_id"] = first_source.id
    store.save_distill_projection(first_record)
    store.save_snapshot(second_source, second_chunks)

    assert store.get_distill_projection(
        first_source.id,
        first_source.source_revision,
        record_version=DISTILL_INCREMENTAL_PROJECTION,
    ) == first_record
    assert store.get_latest_prior_distill_projection(
        second_source.id,
        second_source.source_revision,
        record_version=DISTILL_INCREMENTAL_PROJECTION,
    ) == first_record

    audit = store.hard_delete_revisions(
        [(first_source.id, first_source.source_revision)],
        project_name=first_source.project_name,
        reason="test",
    )
    assert audit["counts"]["semantic_projections"] == 1
    assert store.get_distill_projection(
        first_source.id,
        first_source.source_revision,
        record_version=DISTILL_INCREMENTAL_PROJECTION,
    ) is None
    store.close()


def test_projection_cache_does_not_regress_when_older_job_finishes_last(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path)
    first_value = "User: first\n\nAssistant: done\n"
    second_value = first_value + "User: second\n\nAssistant: done again\n"
    first_source, first_chunks = _projection_snapshot(first_value)
    second_source, second_chunks = _projection_snapshot(second_value)
    store.save_snapshot(first_source, first_chunks)
    store.save_snapshot(second_source, second_chunks)

    _content, _summary, first_record = build_append_aware_distill_projection(
        first_value,
        source_revision=first_source.source_revision,
        source_bytes=first_value.encode("utf-8"),
    )
    _content, _summary, second_record = build_append_aware_distill_projection(
        second_value,
        source_revision=second_source.source_revision,
        source_bytes=second_value.encode("utf-8"),
        previous_projection=first_record,
        previous_source_bytes=first_value.encode("utf-8"),
    )
    first_record["source_id"] = first_source.id
    second_record["source_id"] = second_source.id
    store.save_distill_projection(second_record)
    store.save_distill_projection(first_record)

    assert store.get_distill_projection(
        second_source.id,
        second_source.source_revision,
        record_version=DISTILL_INCREMENTAL_PROJECTION,
    ) == second_record
    assert store.get_distill_projection(
        first_source.id,
        first_source.source_revision,
        record_version=DISTILL_INCREMENTAL_PROJECTION,
    ) is None
    store.close()
