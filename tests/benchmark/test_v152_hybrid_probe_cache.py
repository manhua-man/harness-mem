from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "benchmarks"
    / "scripts"
    / "v152_hybrid_probe_cache.py"
)
SPEC = importlib.util.spec_from_file_location("v152_hybrid_probe_cache", SCRIPT_PATH)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_parse_combo_reads_name_and_weights():
    assert probe.parse_combo("trial:3:5") == ("trial", 3.0, 5.0)


def test_has_temporal_hint_detects_temporal_or_aggregate_queries():
    assert probe.has_temporal_hint("How many workshops did I attend in the past month?")
    assert not probe.has_temporal_hint("Any tips for my phone battery life?")


def test_score_cached_case_can_reserve_fts_rows():
    case = {
        "question": "How many workshops did I attend in the past month?",
        "question_type": "multi-session",
        "answer_session_ids": ["answer-1", "answer-2"],
        "temporal_hint": True,
        "candidates": [
            {
                "id": "noise",
                "session_id": "noise",
                "fts_rank": -1,
                "vec_rank": 0,
                "fts_match_count": 1,
                "fts_component": 0.0,
                "vec_component": 0.03,
            },
            {
                "id": "answer-obs-1",
                "session_id": "answer-1",
                "fts_rank": 0,
                "vec_rank": 4,
                "fts_match_count": 3,
                "fts_component": 0.01,
                "vec_component": 0.001,
            },
            {
                "id": "answer-obs-2",
                "session_id": "answer-2",
                "fts_rank": 1,
                "vec_rank": 5,
                "fts_match_count": 2,
                "fts_component": 0.009,
                "vec_component": 0.001,
            },
        ],
    }

    baseline = probe.score_cached_case(
        case,
        fts_weight=2.0,
        vector_weight=6.0,
        top_k=2,
    )
    rescued = probe.score_cached_case(
        case,
        fts_weight=2.0,
        vector_weight=6.0,
        top_k=2,
        reserve_fts=2,
        reserve_match_count_min=2,
        temporal_only=True,
    )

    assert baseline == 0.5
    assert rescued == 1.0


def test_summarize_cache_scores_reports_avg_and_per_type():
    cache = {
        "top_k": 2,
        "cases": [
            {
                "question": "How many workshops did I attend in the past month?",
                "question_type": "multi-session",
                "answer_session_ids": ["answer-1", "answer-2"],
                "temporal_hint": True,
                "candidates": [
                    {
                        "id": "noise",
                        "session_id": "noise",
                        "fts_rank": -1,
                        "vec_rank": 0,
                        "fts_match_count": 1,
                        "fts_component": 0.0,
                        "vec_component": 0.03,
                    },
                    {
                        "id": "answer-obs-1",
                        "session_id": "answer-1",
                        "fts_rank": 0,
                        "vec_rank": 4,
                        "fts_match_count": 3,
                        "fts_component": 0.01,
                        "vec_component": 0.001,
                    },
                    {
                        "id": "answer-obs-2",
                        "session_id": "answer-2",
                        "fts_rank": 1,
                        "vec_rank": 5,
                        "fts_match_count": 2,
                        "fts_component": 0.009,
                        "vec_component": 0.001,
                    },
                ],
            }
        ],
    }

    summary = probe.summarize_cache_scores(
        cache,
        [("baseline", 2.0, 6.0)],
        reserve_fts=2,
        reserve_match_count_min=2,
        temporal_only=True,
    )

    assert summary["variants"]["baseline"]["avg_recall"] == 1.0
    assert summary["variants"]["baseline"]["per_type"]["multi-session"] == 1.0
