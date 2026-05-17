"""Build and replay cached hybrid-search probe data for v1.5.2 tuning.

The expensive part of tuning the hybrid retriever is rebuilding a temporary
SQLite corpus and recomputing vector candidates for every experiment. This
script pays that cost once, stores the per-case candidate components, and then
lets us replay different fusion weights or FTS reservation heuristics quickly.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from harness_mem.tools.longmemeval import (
    BenchVerbatimStore,
    RealHybridSearch,
    _session_doc_for_query,
    compute_recall,
)

TEMPORAL_HINT_RE = re.compile(
    r"how many|how much|total|order|first|last|ago|week|weeks|month|months|"
    r"year|years|past|between",
    re.IGNORECASE,
)


def parse_combo(raw: str) -> tuple[str, float, float]:
    """Parse `name:fts_weight:vector_weight` CLI combos."""
    name, fts_raw, vec_raw = raw.split(":", 2)
    return name, float(fts_raw), float(vec_raw)


def has_temporal_hint(question: str) -> bool:
    """Heuristic gate for temporal / aggregate style questions."""
    return bool(TEMPORAL_HINT_RE.search(question))


def _build_case_payload(entry: dict) -> tuple[list[str], list[str], dict[str, str]]:
    corpus_ids: list[str] = []
    corpus_texts: list[str] = []
    corpus_dates: dict[str, str] = {}
    question = entry["question"]
    haystack_session_ids = entry["haystack_session_ids"]
    haystack_sessions = entry["haystack_sessions"]
    haystack_dates = entry.get("haystack_dates", [""] * len(haystack_session_ids))

    for sess_id, session, date in zip(haystack_session_ids, haystack_sessions, haystack_dates):
        doc = _session_doc_for_query(session, question)
        if not doc:
            continue
        corpus_ids.append(sess_id)
        corpus_texts.append(doc)
        corpus_dates[sess_id] = date
    return corpus_ids, corpus_texts, corpus_dates


def _build_temp_store(entry: dict) -> tuple[str, Path]:
    corpus_ids, corpus_texts, corpus_dates = _build_case_payload(entry)
    tmpdir = tempfile.mkdtemp(prefix="hm_probe_cache_")
    db_path = Path(tmpdir) / "bench.sqlite"
    store = BenchVerbatimStore(str(db_path))
    for sess_id, text in zip(corpus_ids, corpus_texts):
        timestamp = corpus_dates.get(sess_id, datetime.now(timezone.utc).isoformat())
        store.add(str(uuid4()), sess_id, text, timestamp)
    return tmpdir, db_path


def build_probe_cache(
    dataset_path: Path,
    *,
    baseline_path: Path | None = None,
    failed_only: bool = False,
    top_k: int = 5,
) -> dict:
    """Precompute candidate components for later replay experiments."""
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    selected_entries = dataset
    if failed_only:
        if baseline_path is None:
            raise ValueError("baseline_path is required when failed_only=True")
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        failed_ids = {
            case["question_id"]
            for case in baseline.get("results", [])
            if case.get("recall", 1.0) < 1.0
        }
        selected_entries = [
            entry for entry in dataset
            if entry["question_id"] in failed_ids
        ]

    searcher = RealHybridSearch()
    layer = searcher._layer
    cases: list[dict] = []

    for entry in selected_entries:
        tmpdir, db_path = _build_temp_store(entry)
        try:
            searcher.set_path(str(db_path))
            question = entry["question"]
            fts_results = layer._sqlite.search("observations", question, limit=top_k * 10)
            vector_state = layer._score_vector_candidates(
                question,
                "observations",
                limit=top_k,
                extra_where=None,
                extra_params=(),
                seed_rows=fts_results,
            )

            if vector_state is None:
                candidate_by_id = {row["id"]: row for row in fts_results}
                sim_scores: dict[str, float] = {}
                vec_rank: dict[str, int] = {}
            else:
                candidate_by_id, sim_scores, vec_rank = vector_state

            fts_rank = {
                row["id"]: rank
                for rank, row in enumerate(fts_results)
            }
            fts_confidence = layer._confidence_factors_from_scores(
                {
                    row["id"]: (
                        abs(float(row.get("_fts_score_total", row.get("_fts_score", 0.0))))
                        * max(1, int(row.get("_fts_match_count", 1)))
                    )
                    for row in fts_results
                },
                exponent=layer._fts_confidence_exponent,
            )
            vector_confidence = layer._confidence_factors_from_scores(
                sim_scores,
                exponent=layer._vector_confidence_exponent,
            )

            candidates: list[dict] = []
            for row_id, row in candidate_by_id.items():
                fts_component = 0.0
                if row_id in fts_rank:
                    fts_component = (
                        fts_confidence.get(row_id, 1.0)
                        / (layer._rrf_k + fts_rank[row_id])
                    )

                vec_component = 0.0
                if row_id in vec_rank:
                    vec_component = (
                        vector_confidence.get(row_id, 1.0)
                        / (layer._rrf_k + vec_rank[row_id])
                    )

                candidates.append(
                    {
                        "id": row_id,
                        "session_id": row["session_id"],
                        "fts_rank": fts_rank.get(row_id, -1),
                        "vec_rank": vec_rank.get(row_id, -1),
                        "fts_match_count": int(row.get("_fts_match_count", 1)),
                        "fts_score_total": float(
                            row.get("_fts_score_total", row.get("_fts_score", 0.0))
                        ),
                        "vec_sim": float(sim_scores.get(row_id, 0.0)),
                        "fts_component": fts_component,
                        "vec_component": vec_component,
                    }
                )

            baseline_ranked = sorted(
                candidates,
                key=lambda candidate: (
                    layer._fts_weight * candidate["fts_component"]
                    + layer._vector_weight * candidate["vec_component"]
                ),
                reverse=True,
            )[:top_k]
            baseline_recall = compute_recall(
                [candidate["session_id"] for candidate in baseline_ranked],
                set(entry["answer_session_ids"]),
            )

            cases.append(
                {
                    "question_id": entry["question_id"],
                    "question_type": entry["question_type"],
                    "question": question,
                    "answer_session_ids": entry["answer_session_ids"],
                    "temporal_hint": has_temporal_hint(question),
                    "baseline_recall": baseline_recall,
                    "candidates": candidates,
                }
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_path": str(dataset_path),
        "baseline_path": str(baseline_path) if baseline_path is not None else None,
        "failed_only": failed_only,
        "top_k": top_k,
        "current_weights": {
            "fts_weight": layer._fts_weight,
            "vector_weight": layer._vector_weight,
        },
        "case_count": len(cases),
        "cases": cases,
    }


def _fill_reserved(
    reserved: list[dict],
    ranked: list[dict],
    *,
    top_k: int,
) -> list[dict]:
    final: list[dict] = []
    seen_ids: set[str] = set()
    for candidate in reserved:
        if candidate["id"] in seen_ids:
            continue
        seen_ids.add(candidate["id"])
        final.append(candidate)
        if len(final) >= top_k:
            return final
    for candidate in ranked:
        if candidate["id"] in seen_ids:
            continue
        seen_ids.add(candidate["id"])
        final.append(candidate)
        if len(final) >= top_k:
            break
    return final


def score_cached_case(
    case: dict,
    *,
    fts_weight: float,
    vector_weight: float,
    top_k: int,
    reserve_fts: int = 0,
    reserve_match_count_min: int = 0,
    temporal_only: bool = False,
) -> float:
    """Replay one cached case with alternate fusion settings."""
    ranked = sorted(
        case["candidates"],
        key=lambda candidate: (
            fts_weight * candidate["fts_component"]
            + vector_weight * candidate["vec_component"]
        ),
        reverse=True,
    )

    final_rows = ranked[:top_k]
    should_reserve = reserve_fts > 0 and (
        not temporal_only or bool(case.get("temporal_hint"))
    )
    if should_reserve:
        reserved = [
            candidate
            for candidate in sorted(
                case["candidates"],
                key=lambda candidate: (
                    candidate["fts_rank"] < 0,
                    candidate["fts_rank"],
                ),
            )
            if candidate["fts_rank"] >= 0
            and candidate["fts_match_count"] >= reserve_match_count_min
        ][:reserve_fts]
        final_rows = _fill_reserved(reserved, ranked, top_k=top_k)

    return compute_recall(
        [candidate["session_id"] for candidate in final_rows],
        set(case["answer_session_ids"]),
    )


def summarize_cache_scores(
    cache: dict,
    combos: list[tuple[str, float, float]],
    *,
    reserve_fts: int = 0,
    reserve_match_count_min: int = 0,
    temporal_only: bool = False,
) -> dict:
    """Score multiple replay configs against the same cached candidate set."""
    top_k = int(cache["top_k"])
    per_combo_scores: dict[str, list[float]] = {
        name: [] for name, _, _ in combos
    }
    per_combo_types: dict[str, dict[str, list[float]]] = {
        name: defaultdict(list) for name, _, _ in combos
    }

    for case in cache["cases"]:
        question_type = case["question_type"]
        for name, fts_weight, vector_weight in combos:
            recall = score_cached_case(
                case,
                fts_weight=fts_weight,
                vector_weight=vector_weight,
                top_k=top_k,
                reserve_fts=reserve_fts,
                reserve_match_count_min=reserve_match_count_min,
                temporal_only=temporal_only,
            )
            per_combo_scores[name].append(recall)
            per_combo_types[name][question_type].append(recall)

    return {
        "cache_path": cache.get("cache_path"),
        "top_k": top_k,
        "reserve_fts": reserve_fts,
        "reserve_match_count_min": reserve_match_count_min,
        "temporal_only": temporal_only,
        "variants": {
            name: {
                "avg_recall": (
                    sum(per_combo_scores[name]) / len(per_combo_scores[name])
                    if per_combo_scores[name] else 0.0
                ),
                "per_type": {
                    question_type: sum(values) / len(values)
                    for question_type, values in sorted(per_combo_types[name].items())
                },
            }
            for name, _, _ in combos
        },
    }


def _cmd_build(args: argparse.Namespace) -> None:
    cache = build_probe_cache(
        Path(args.dataset),
        baseline_path=Path(args.baseline) if args.baseline else None,
        failed_only=args.failed_only,
        top_k=args.top_k,
    )
    out_path = Path(args.out_cache)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    print(f"Wrote probe cache to {out_path}")


def _cmd_score(args: argparse.Namespace) -> None:
    cache_path = Path(args.cache)
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache["cache_path"] = str(cache_path)
    combos = [parse_combo(raw) for raw in args.combo]
    summary = summarize_cache_scores(
        cache,
        combos,
        reserve_fts=args.reserve_fts,
        reserve_match_count_min=args.reserve_match_count_min,
        temporal_only=args.temporal_only,
    )

    for name, variant in summary["variants"].items():
        print(f"{name} avg_recall {variant['avg_recall']:.6f}")
        for question_type, avg in variant["per_type"].items():
            print(f"  {question_type} {avg:.6f}")

    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Wrote score summary to {out_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cache and replay v1.5.2 hybrid search probe data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build probe cache")
    build_parser.add_argument("--dataset", required=True, help="Path to LongMemEval JSON")
    build_parser.add_argument("--out-cache", required=True, help="Output cache path")
    build_parser.add_argument("--baseline", help="Optional baseline result JSON")
    build_parser.add_argument("--failed-only", action="store_true", help="Cache only failed baseline cases")
    build_parser.add_argument("--top-k", type=int, default=5, help="Top-k cutoff")
    build_parser.set_defaults(func=_cmd_build)

    score_parser = subparsers.add_parser("score", help="Replay probe cache")
    score_parser.add_argument("--cache", required=True, help="Path to probe cache JSON")
    score_parser.add_argument(
        "--combo",
        action="append",
        required=True,
        help="Variant spec: name:fts_weight:vector_weight",
    )
    score_parser.add_argument("--reserve-fts", type=int, default=0, help="Reserved FTS rows")
    score_parser.add_argument(
        "--reserve-match-count-min",
        type=int,
        default=0,
        help="Minimum _fts_match_count for reserved rows",
    )
    score_parser.add_argument(
        "--temporal-only",
        action="store_true",
        help="Apply FTS reservation only when the question matches temporal/aggregate hints",
    )
    score_parser.add_argument("--out-json", help="Optional output JSON summary path")
    score_parser.set_defaults(func=_cmd_score)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
