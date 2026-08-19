from pathlib import Path

import pytest

from harness_mem.core.schemas.knowledge import KnowledgeEntry
from harness_mem.qualification.archive_cohort_acceptance import (
    _assert_isolated_paths,
    _evaluate_promotion_oracle,
    _load_promotion_oracle,
    _quality_findings,
)
from harness_mem.knowledge_renderer import render_knowledge_markdown


def test_quality_accepts_clean_title_statement_projection() -> None:
    entries = [
        KnowledgeEntry(
            project_name="harness-mem",
            module_path=["会话生命周期与 Hook"],
            title="Hook 终态绑定实际作业",
            statement="Hook 回执必须对应同一会话的实际作业与最终 Note。",
        )
    ]
    markdown = render_knowledge_markdown("harness-mem", entries)

    quality = _quality_findings(entries, markdown)

    assert quality["passed"] is True
    assert quality["projection_keys"] == ["statement", "title"]
    assert quality["forbidden_headings"] == []


def test_quality_accepts_one_obligation_that_lists_required_fields() -> None:
    entries = [
        KnowledgeEntry(
            project_name="harness-mem",
            module_path=["会话接入与生命周期"],
            title="最终会话审查记录字段",
            statement=(
                "最终会话审查记录必须包含会话标识、作业标识、"
                "Provider 回执、Note 路径和终态。"
            ),
        )
    ]

    quality = _quality_findings(
        entries,
        render_knowledge_markdown("harness-mem", entries),
    )

    assert quality["passed"] is True
    assert quality["broad_item_warnings"] == []


def test_quality_rejects_multiple_pipeline_actions_as_one_item() -> None:
    entries = [
        KnowledgeEntry(
            project_name="harness-mem",
            module_path=["归纳吸收"],
            title="完整处理管线",
            statement="抓取原文、保存证据、规范化候选、验证协议、发布知识。",
        )
    ]

    quality = _quality_findings(
        entries,
        render_knowledge_markdown("harness-mem", entries),
    )

    assert quality["passed"] is False
    assert quality["broad_item_warnings"][0]["title"] == "完整处理管线"


def test_quality_rejects_internal_heading_and_audit_leak() -> None:
    entries = [
        KnowledgeEntry(
            project_name="harness-mem",
            module_path=["稳定操作规则"],
            title="候选处理",
            statement="普通结果不得展示 candidate_id。",
        )
    ]
    markdown = render_knowledge_markdown("harness-mem", entries)

    quality = _quality_findings(entries, markdown)

    assert quality["passed"] is False
    assert quality["forbidden_headings"] == ["稳定操作规则"]
    assert quality["leaked_markers"] == ["candidate_id"]


def test_acceptance_output_must_not_overlap_protected_roots(
    tmp_path: Path,
) -> None:
    source = tmp_path / "archives"
    real_data = tmp_path / "real-data"
    real_notes = tmp_path / "real-notes"

    with pytest.raises(ValueError, match="must not overlap"):
        _assert_isolated_paths(
            output_root=real_data / "nested",
            source_archive_dir=source,
            real_data_dir=real_data,
            real_notes_dir=real_notes,
        )

    _assert_isolated_paths(
        output_root=tmp_path / "isolated",
        source_archive_dir=source,
        real_data_dir=real_data,
        real_notes_dir=real_notes,
    )


def test_promotion_oracle_compares_extracted_verified_and_assimilated() -> None:
    oracle = {
        "schema_version": 1,
        "project_name": "demo",
        "sessions": [
            {
                "session_id": "session-1",
                "point_count": 2,
                "answer_status_counts": {"ANSWERED": 2},
                "disposition_counts": {"add": 1, "no_write": 1},
                "promotions": [
                    {
                        "title": "Preserve original evidence",
                        "statement_terms": ["original", "normalization"],
                    }
                ],
            }
        ],
    }
    result = _evaluate_promotion_oracle(
        oracle=oracle,
        job_promotions={
            "session-1": {
                "points": [
                    {
                        "answer_status": "ANSWERED",
                        "disposition": "add",
                        "canonical_truth_ids": ["knowledge-1"],
                    },
                    {"answer_status": "ANSWERED", "disposition": "no_write"},
                ],
                "answer_packet": {
                    "promoted_items": [
                        {
                            "title": "Preserve original evidence",
                            "fact": "Keep original evidence before normalization.",
                        }
                    ]
                },
            }
        },
        truth_lineage=[
            {
                "id": "knowledge-1",
                "title": "Preserve original evidence",
                "statement": "Keep original evidence before normalization.",
            }
        ],
    )

    assert result["passed"] is True
    assert result["sessions"][0]["extracted"] == {
        "point_count": 2,
        "passed": True,
    }
    assert result["sessions"][0]["missing"] == []
    assert result["sessions"][0]["unexpected"] == []


def test_promotion_oracle_reports_missing_and_unexpected_points() -> None:
    result = _evaluate_promotion_oracle(
        oracle={
            "sessions": [
                {
                    "session_id": "session-1",
                    "point_count": 1,
                    "answer_status_counts": {"ANSWERED": 1},
                    "disposition_counts": {"add": 1},
                    "promotions": [{"title": "Expected", "statement_terms": []}],
                }
            ]
        },
        job_promotions={
            "session-1": {
                "points": [{"answer_status": "ANSWERED", "disposition": "add"}],
                "answer_packet": {
                    "promoted_items": [{"title": "Unexpected", "fact": "Other."}]
                },
            }
        },
    )

    assert result["passed"] is False
    assert result["sessions"][0]["missing"] == ["Expected"]
    assert result["sessions"][0]["unexpected"] == ["Unexpected"]


def test_promotion_oracle_matches_semantic_points_across_overlapping_sessions() -> None:
    result = _evaluate_promotion_oracle(
        oracle={
            "sessions": [
                {
                    "session_id": "session-1",
                    "point_count": {"min": 1, "max": 3},
                    "allowed_answer_statuses": ["ANSWERED"],
                    "allowed_dispositions": ["add", "confirm"],
                    "promotion_count": {"min": 1, "max": 3},
                },
                {
                    "session_id": "session-2",
                    "point_count": {"min": 1, "max": 3},
                    "allowed_answer_statuses": ["ANSWERED"],
                    "allowed_dispositions": ["add", "confirm"],
                    "promotion_count": {"min": 1, "max": 3},
                },
            ],
            "promotion_groups": [
                {
                    "name": "shared architecture",
                    "session_ids": ["session-1", "session-2"],
                    "expected_points": [
                        {
                            "key": "content_hash_revision",
                            "match_any": [
                                ["content-hash", "revision"],
                                ["内容哈希", "revision"],
                            ],
                        },
                        {
                            "key": "lossless_reconstruction",
                            "match_any": [["lossless", "reconstruct"]],
                        },
                    ],
                }
            ],
        },
        job_promotions={
            "session-1": {
                "points": [
                    {
                        "answer_status": "ANSWERED",
                        "disposition": "add",
                        "canonical_truth_ids": ["knowledge-1"],
                    }
                ],
                "answer_packet": {
                    "promoted_items": [
                        {
                            "title": "Content-hash revision identity",
                            "fact": "Changed content receives a content-hash revision.",
                        }
                    ]
                },
            },
            "session-2": {
                "points": [
                    {
                        "answer_status": "ANSWERED",
                        "disposition": "add",
                        "canonical_truth_ids": ["knowledge-2"],
                    }
                ],
                "answer_packet": {
                    "promoted_items": [
                        {
                            "title": "Lossless session reconstruction",
                            "fact": "Session chunks must reconstruct the lossless source.",
                        }
                    ]
                },
            },
        },
        truth_lineage=[
            {
                "id": "knowledge-1",
                "title": "Content-hash revision identity",
                "statement": "Changed content receives a content-hash revision.",
            },
            {
                "id": "knowledge-2",
                "title": "Lossless session reconstruction",
                "statement": "Session chunks must reconstruct the lossless source.",
            },
        ],
    )

    assert result["passed"] is True
    assert result["promotion_groups"][0]["missing"] == []
    assert result["promotion_groups"][0]["unexpected"] == []


def test_promotion_oracle_normalizes_harmless_token_separators() -> None:
    result = _evaluate_promotion_oracle(
        oracle={
            "sessions": [
                {
                    "session_id": "session-1",
                    "point_count": 1,
                    "allowed_answer_statuses": ["ANSWERED"],
                    "allowed_dispositions": ["add"],
                    "promotion_count": 1,
                }
            ],
            "promotion_groups": [
                {
                    "name": "candidate identity",
                    "session_ids": ["session-1"],
                    "expected_points": [
                        {
                            "key": "stable_candidate_identity",
                            "match_any": [["source_revision", "normalized_claim"]],
                        }
                    ],
                }
            ],
        },
        job_promotions={
            "session-1": {
                "points": [
                    {
                        "answer_status": "ANSWERED",
                        "disposition": "add",
                        "canonical_truth_ids": ["knowledge-1"],
                    }
                ],
                "answer_packet": {
                    "promoted_items": [
                        {
                            "title": "Candidate idempotency key",
                            "fact": "The key includes source revision and normalized claim.",
                        }
                    ]
                },
            }
        },
        truth_lineage=[
            {
                "id": "knowledge-1",
                "title": "Candidate idempotency key",
                "statement": "The key includes source revision and normalized claim.",
            }
        ],
    )

    assert result["passed"] is True


def test_promotion_oracle_resolves_predecessor_knowledge_id_from_version() -> None:
    result = _evaluate_promotion_oracle(
        oracle={
            "sessions": [
                {
                    "session_id": "session-1",
                    "point_count": 1,
                    "allowed_answer_statuses": ["ANSWERED"],
                    "allowed_dispositions": ["add"],
                    "promotion_count": 1,
                }
            ],
            "promotion_groups": [
                {
                    "name": "review lineage",
                    "session_ids": ["session-1"],
                    "expected_points": [
                        {
                            "key": "review",
                            "match_any": [["session", "review"]],
                        }
                    ],
                }
            ],
        },
        job_promotions={
            "session-1": {
                "points": [
                    {
                        "answer_status": "ANSWERED",
                        "disposition": "add",
                        "canonical_truth_ids": ["old-knowledge"],
                    }
                ],
                "answer_packet": {
                    "promoted_items": [
                        {
                            "title": "Session review",
                            "fact": "Complete session review before promotion.",
                        }
                    ]
                },
            }
        },
        truth_lineage=[
            {
                "id": "version-snapshot",
                "knowledge_id": "old-knowledge",
                "title": "Session review",
                "statement": "Complete session review before promotion.",
            }
        ],
    )

    assert result["passed"] is True
    assert result["sessions"][0]["assimilated"]["unresolved_truth_ids"] == []


def test_promotion_oracle_does_not_reuse_one_item_for_multiple_expected_points() -> None:
    result = _evaluate_promotion_oracle(
        oracle={
            "sessions": [
                {
                    "session_id": "session-1",
                    "point_count": 1,
                    "allowed_answer_statuses": ["ANSWERED"],
                    "allowed_dispositions": ["add"],
                    "promotion_count": 1,
                }
            ],
            "promotion_groups": [
                {
                    "name": "atomic architecture",
                    "session_ids": ["session-1"],
                    "expected_points": [
                        {
                            "key": "revision_identity",
                            "match_any": [["revision", "identity"]],
                        },
                        {
                            "key": "lossless_reconstruction",
                            "match_any": [["lossless", "reconstruction"]],
                        },
                    ],
                }
            ],
        },
        job_promotions={
            "session-1": {
                "points": [
                    {
                        "answer_status": "ANSWERED",
                        "disposition": "add",
                        "canonical_truth_ids": ["knowledge-1"],
                    }
                ],
                "answer_packet": {
                    "promoted_items": [
                        {
                            "title": "Revision identity and lossless reconstruction",
                            "fact": (
                                "Content-hash revision identity supports lossless "
                                "reconstruction."
                            ),
                        }
                    ]
                },
            }
        },
        truth_lineage=[
            {
                "id": "knowledge-1",
                "title": "Revision identity and lossless reconstruction",
                "statement": (
                    "Content-hash revision identity supports lossless reconstruction."
                ),
            }
        ],
    )

    group = result["promotion_groups"][0]
    assert result["passed"] is False
    assert len(group["missing"]) == 1
    assert sum(len(titles) for titles in group["matched"].values()) == 1


def test_promotion_oracle_requires_exact_frozen_cohort(tmp_path: Path) -> None:
    oracle_path = tmp_path / "oracle.json"
    oracle_path.write_text(
        '{"schema_version":1,"project_name":"demo",'
        '"reviewed_at":"2026-08-19T00:00:00+00:00",'
        '"review_basis":"test review","sessions":['
        '{"session_id":"session-1","source_sha256":"a"}]}',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="one row per cohort session"):
        _load_promotion_oracle(
            oracle_path,
            project_name="demo",
            cohort=[
                {"session_id": "session-1", "source_sha256": "a"},
                {"session_id": "session-2", "source_sha256": "b"},
            ],
        )


def test_promotion_oracle_binds_reviewed_source_digest(tmp_path: Path) -> None:
    oracle_path = tmp_path / "oracle.json"
    oracle_path.write_text(
        '{"schema_version":1,"project_name":"demo",'
        '"reviewed_at":"2026-08-19T00:00:00+00:00",'
        '"review_basis":"test review","sessions":['
        '{"session_id":"session-1","source_sha256":"old",'
        '"promotions":[]}]}',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="source digest"):
        _load_promotion_oracle(
            oracle_path,
            project_name="demo",
            cohort=[{"session_id": "session-1", "source_sha256": "new"}],
        )


def test_promotion_oracle_requires_explicit_session_expectations(tmp_path: Path) -> None:
    oracle_path = tmp_path / "oracle.json"
    oracle_path.write_text(
        '{"schema_version":1,"project_name":"demo",'
        '"reviewed_at":"2026-08-19T00:00:00+00:00",'
        '"review_basis":"test review","sessions":['
        '{"session_id":"session-1","source_sha256":"a",'
        '"point_count":0,"answer_status_counts":{},'
        '"disposition_counts":{},"promotion_count":0}]}',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="exact promotions or promotion_group_names"):
        _load_promotion_oracle(
            oracle_path,
            project_name="demo",
            cohort=[{"session_id": "session-1", "source_sha256": "a"}],
        )


def test_promotion_oracle_accepts_explicit_group_scoped_session(tmp_path: Path) -> None:
    oracle_path = tmp_path / "oracle.json"
    oracle_path.write_text(
        '{"schema_version":1,"project_name":"demo",'
        '"reviewed_at":"2026-08-19T00:00:00+00:00",'
        '"review_basis":"test review","sessions":['
        '{"session_id":"session-1","source_sha256":"a",'
        '"point_count":{"min":0,"max":12},'
        '"allowed_answer_statuses":["ANSWERED","STALE"],'
        '"allowed_dispositions":["add","reject"],'
        '"promotion_count":{"min":0,"max":12},'
        '"promotion_group_names":["architecture"]}],'
        '"promotion_groups":[{"name":"architecture",'
        '"session_ids":["session-1"],"expected_points":['
        '{"key":"lossless","match_any":[["lossless","session"]]}]}]}',
        encoding="utf-8",
    )

    loaded = _load_promotion_oracle(
        oracle_path,
        project_name="demo",
        cohort=[{"session_id": "session-1", "source_sha256": "a"}],
    )

    assert loaded["sessions"][0]["promotion_group_names"] == ["architecture"]
