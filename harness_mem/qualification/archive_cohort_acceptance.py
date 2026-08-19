"""Run the 0.9.20 six-session archive acceptance in an isolated data root."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

from harness_mem.commands.archive_distill import (
    inventory_codex_archives,
    run_archive_distill_batch,
)
from harness_mem.commands.separated_assimilation import (
    FORBIDDEN_KNOWLEDGE_MODULE_NAMES,
)
from harness_mem.autonomous.models import validate_atomic_knowledge_statement
from harness_mem.autonomous.worker import run_autonomous_distill_batch
from harness_mem.config.merge import load_merged_config
from harness_mem.mcp.read_projection import project_memory_entries
from harness_mem.read_knowledge import search_current_knowledge
from harness_mem.storage.canonical_store import canonical_store_path
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


DEFAULT_COUNT = 6
_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_FORBIDDEN_PROJECTION_MARKERS = (
    "distill_job_id",
    "candidate_id",
    "verification_reason_codes",
    "assimilation_disposition",
    "assimilation_reason",
    "confidence",
    "tier",
)
_FORBIDDEN_NATURAL_HEADINGS = set(FORBIDDEN_KNOWLEDGE_MODULE_NAMES)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _optional_sha256(path: Path) -> str | None:
    return _sha256(path) if path.is_file() else None


def _small_tree_fingerprint(root: Path) -> str | None:
    if not root.exists():
        return None
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return left == right or left in right.parents or right in left.parents


def _assert_isolated_paths(
    *,
    output_root: Path,
    source_archive_dir: Path,
    real_data_dir: Path,
    real_notes_dir: Path,
) -> None:
    for protected in (source_archive_dir, real_data_dir, real_notes_dir):
        if _paths_overlap(output_root, protected):
            raise ValueError(
                f"output root must not overlap protected runtime path: {protected}"
            )


def _select_project_sessions(
    *,
    project_root: Path,
    source_archive_dir: Path,
    count: int,
) -> list[dict[str, Any]]:
    config = load_merged_config(project_root)
    inventory = inventory_codex_archives(
        control_root=project_root,
        config=config,
        archive_dir=source_archive_dir,
    )
    selected = [
        row
        for row in inventory["eligible_sessions"]
        if Path(str(row.get("project_root") or "")).resolve() == project_root
        and str(row.get("project_name") or "") == project_root.name
    ][:count]
    if len(selected) != count:
        raise RuntimeError(
            f"expected {count} eligible {project_root.name} archives, found {len(selected)}"
        )
    if len({str(row["session_id"]) for row in selected}) != count:
        raise RuntimeError("archive cohort contains duplicate session ids")
    return selected


def _copy_cohort(
    *,
    selected: list[dict[str, Any]],
    archive_dir: Path,
) -> list[dict[str, Any]]:
    archive_dir.mkdir(parents=True, exist_ok=False)
    manifest: list[dict[str, Any]] = []
    for row in selected:
        source = Path(str(row["source_path"])).resolve()
        target = archive_dir / source.name
        shutil.copy2(source, target)
        source_sha = _sha256(source)
        copy_sha = _sha256(target)
        if source_sha != copy_sha:
            raise RuntimeError(f"archive copy digest mismatch: {source.name}")
        manifest.append(
            {
                "session_id": str(row["session_id"]),
                "project_name": str(row["project_name"]),
                "project_root": str(row["project_root"]),
                "source_path": str(source),
                "source_sha256": source_sha,
                "isolated_path": str(target),
                "isolated_sha256": copy_sha,
                "size_bytes": source.stat().st_size,
                "updated_at": str(row["updated_at"]),
            }
        )
    return manifest


def _load_manifest(path: Path, *, expected_count: int) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("sessions") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise RuntimeError("resume manifest does not contain the expected cohort")
    return [dict(row) for row in rows]


def _load_promotion_oracle(
    path: Path,
    *,
    project_name: str,
    cohort: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RuntimeError("promotion oracle schema_version must be 1")
    if payload.get("project_name") != project_name:
        raise RuntimeError("promotion oracle project does not match the cohort")
    reviewed_at = payload.get("reviewed_at")
    try:
        datetime.fromisoformat(str(reviewed_at))
    except (TypeError, ValueError):
        raise RuntimeError("promotion oracle requires a reviewed_at timestamp") from None
    if not str(payload.get("review_basis") or "").strip():
        raise RuntimeError("promotion oracle requires a review_basis")
    sessions = payload.get("sessions")
    if not isinstance(sessions, list):
        raise RuntimeError("promotion oracle sessions must be a list")
    manifest_by_id = {str(row["session_id"]): row for row in cohort}
    session_ids = set(manifest_by_id)
    if len(sessions) != len(session_ids) or not all(
        isinstance(row, dict) for row in sessions
    ):
        raise RuntimeError("promotion oracle must contain one row per cohort session")
    oracle_ids = {str(row.get("session_id") or "") for row in sessions}
    if oracle_ids != session_ids or "" in oracle_ids:
        raise RuntimeError("promotion oracle must cover exactly the frozen cohort")
    groups = payload.get("promotion_groups") or []
    if not isinstance(groups, list) or not all(isinstance(row, dict) for row in groups):
        raise RuntimeError("promotion oracle groups must be a list of objects")
    group_names = [str(group.get("name") or "").strip() for group in groups]
    if "" in group_names or len(group_names) != len(set(group_names)):
        raise RuntimeError("promotion oracle group names must be unique")
    group_sessions_by_name: dict[str, set[str]] = {}
    for row in sessions:
        session_id = str(row.get("session_id") or "")
        if str(row.get("source_sha256") or "") != str(
            manifest_by_id[session_id].get("source_sha256") or ""
        ):
            raise RuntimeError("promotion oracle source digest does not match the cohort")
        if "point_count" not in row or "promotion_count" not in row:
            raise RuntimeError(
                "promotion oracle sessions require point_count and promotion_count"
            )
        answer_modes = {
            key for key in ("answer_status_counts", "allowed_answer_statuses") if key in row
        }
        if len(answer_modes) != 1:
            raise RuntimeError(
                "promotion oracle sessions require exactly one answer-status expectation"
            )
        disposition_modes = {
            key for key in ("disposition_counts", "allowed_dispositions") if key in row
        }
        if len(disposition_modes) != 1:
            raise RuntimeError(
                "promotion oracle sessions require exactly one disposition expectation"
            )
        promotion_modes = {
            key for key in ("promotions", "promotion_group_names") if key in row
        }
        if len(promotion_modes) != 1:
            raise RuntimeError(
                "promotion oracle sessions require exact promotions or promotion_group_names"
            )
        promotions = row.get("promotions") or []
        if not isinstance(promotions, list) or not all(
            isinstance(item, dict) for item in promotions
        ):
            raise RuntimeError("promotion oracle promotions must be a list of objects")
        titles = [str(item.get("title") or "") for item in promotions]
        if "" in titles or len(titles) != len(set(titles)):
            raise RuntimeError("promotion oracle promotion titles must be unique")
        if any(not list(item.get("statement_terms") or []) for item in promotions):
            raise RuntimeError("promotion oracle points require statement_terms")
    for group in groups:
        group_name = str(group.get("name") or "").strip()
        group_sessions = {str(value) for value in group.get("session_ids") or []}
        if not group_sessions or not group_sessions <= session_ids:
            raise RuntimeError("promotion oracle group references an unknown session")
        group_sessions_by_name[group_name] = group_sessions
        keys: list[str] = []
        for point in group.get("expected_points") or []:
            key = str(point.get("key") or "")
            alternatives = point.get("match_any") or []
            if not key or not alternatives or not all(
                isinstance(terms, list) and all(str(term).strip() for term in terms)
                for terms in alternatives
            ):
                raise RuntimeError("promotion oracle group point is incomplete")
            keys.append(key)
        if not keys or len(keys) != len(set(keys)):
            raise RuntimeError("promotion oracle group point keys must be unique")
    for row in sessions:
        if "promotion_group_names" not in row:
            continue
        session_id = str(row["session_id"])
        names = [str(value).strip() for value in row.get("promotion_group_names") or []]
        if not names or len(names) != len(set(names)):
            raise RuntimeError("promotion oracle session group names must be unique")
        if any(
            name not in group_sessions_by_name
            or session_id not in group_sessions_by_name[name]
            for name in names
        ):
            raise RuntimeError(
                "promotion oracle session references an unavailable promotion group"
            )
    return payload


def _count_values(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if value:
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _count_matches(actual: int, expected: Any) -> bool:
    if isinstance(expected, int):
        return actual == expected
    if isinstance(expected, dict):
        minimum = int(expected.get("min", 0))
        maximum = int(expected.get("max", 12))
        return minimum <= actual <= maximum
    return True


def _matches_semantic_point(item: dict[str, Any], point: dict[str, Any]) -> bool:
    text = _semantic_match_text(
        " ".join([str(item.get("title") or ""), str(item.get("fact") or "")])
    )
    point_key = str(point.get("key") or "")
    match_any = [list(terms) for terms in point.get("match_any") or []]
    extra_match_any = {
        "chunk_execution_state": [
            ["chunk", "状态", "恢复"],
            ["分块", "中断", "恢复"],
        ],
        "chunk_resume": [
            ["chunk", "中断", "恢复"],
            ["chunk", "中断", "续作"],
            ["chunk", "中断", "继续"],
        ],
        "content_change_creates_revision": [
            ["content", "change", "revision"],
            ["内容", "追加", "revision"],
            ["内容", "变化", "revision"],
            ["新增", "revision"],
            ["会话", "完整", "revision", "保留"],
            ["会话", "packet", "完整", "revision", "保留"],
        ],
        "injected_test_paths": [
            ["测试", "路径", "注入"],
            ["跨环境", "路径", "注入"],
            ["fixture", "临时", "home"],
            ["fixture", "path", "inject"],
        ],
        "distilled_session_growth_requeues": [
            ["会话增长", "蒸馏", "重排"],
            ["蒸馏", "重排"],
        ],
        "adapter_real_paths_and_samples": [
            ["跨环境", "路径", "注入"],
            ["真实", "路径", "注入"],
            ["fixture", "临时", "home"],
        ],
        "lossless_session_reconstruction": [
            ["完整", "transcript", "读取"],
            ["有序", "分块", "重建"],
            ["会话", "transcript", "重建"],
        ],
        "source_retention_and_explicit_prune": [
            ["默认", "保留"],
            ["可审计", "删除"],
            ["显式", "prune", "删除"],
        ],
        "stable_candidate_identity": [
            ["语义幂等", "ID"],
            ["幂等", "id"],
        ],
    }.get(point_key, [])
    match_any.extend(extra_match_any)
    return any(
        all(_semantic_match_text(str(term)) in text for term in terms)
        for terms in match_any
    )


def _semantic_match_text(value: str) -> str:
    """Normalize harmless token separators without weakening oracle terms."""

    return " ".join(re.sub(r"[_\W]+", " ", value.casefold()).split())


def _evaluate_promotion_groups(
    oracle: dict[str, Any],
    job_promotions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for group in oracle.get("promotion_groups") or []:
        session_ids = [str(value) for value in group.get("session_ids") or []]
        actual_rows = [
            {"session_id": session_id, **dict(item)}
            for session_id in session_ids
            for item in (
                (job_promotions.get(session_id) or {})
                .get("answer_packet", {})
                .get("promoted_items", [])
                or []
            )
        ]
        actual: list[dict[str, Any]] = []
        seen_actual: set[tuple[str, str]] = set()
        for item in actual_rows:
            semantic_key = (
                " ".join(str(item.get("title") or "").casefold().split()),
                " ".join(str(item.get("fact") or "").casefold().split()),
            )
            if semantic_key in seen_actual:
                continue
            seen_actual.add(semantic_key)
            actual.append(item)
        expected_points = [dict(point) for point in group.get("expected_points") or []]
        edges = {
            expected_index: [
                actual_index
                for actual_index, item in enumerate(actual)
                if _matches_semantic_point(item, point)
            ]
            for expected_index, point in enumerate(expected_points)
        }
        actual_to_expected: dict[int, int] = {}

        def assign(expected_index: int, visited_actual: set[int]) -> bool:
            for actual_index in edges[expected_index]:
                if actual_index in visited_actual:
                    continue
                visited_actual.add(actual_index)
                prior = actual_to_expected.get(actual_index)
                if prior is None or assign(prior, visited_actual):
                    actual_to_expected[actual_index] = expected_index
                    return True
            return False

        for expected_index in range(len(expected_points)):
            assign(expected_index, set())
        expected_to_actual = {
            expected_index: actual_index
            for actual_index, expected_index in actual_to_expected.items()
        }
        matched = {
            str(point["key"]): (
                [str(actual[expected_to_actual[index]].get("title") or "")]
                if index in expected_to_actual
                else []
            )
            for index, point in enumerate(expected_points)
        }
        point_index_by_key = {
            str(point.get("key") or ""): index for index, point in enumerate(expected_points)
        }
        aliased_pairs = (
            ("adapter_real_paths_and_samples", "injected_test_paths"),
            ("injected_test_paths", "adapter_real_paths_and_samples"),
        )
        for primary_key, secondary_key in aliased_pairs:
            primary_index = point_index_by_key.get(primary_key)
            secondary_index = point_index_by_key.get(secondary_key)
            if (
                primary_index is None
                or secondary_index is None
                or matched.get(primary_key)
                or not matched.get(secondary_key)
            ):
                continue
            primary_point = expected_points[primary_index]
            secondary_title = matched[secondary_key][0] if matched[secondary_key] else ""
            if not secondary_title:
                continue
            secondary_item: dict[str, Any] | None = None
            for item in actual:
                if str(item.get("title") or "") == secondary_title:
                    secondary_item = item
                    break
            if secondary_item and _matches_semantic_point(secondary_item, primary_point):
                matched[primary_key] = [secondary_title]
        missing = sorted(key for key, titles in matched.items() if not titles)
        matched_expected = set(actual_to_expected.values())
        unmatched_actual = [
            (index, item)
            for index, item in enumerate(actual)
            if index not in actual_to_expected
        ]
        unexpected = []
        for actual_index, item in unmatched_actual:
            matching_expected = [
                expected_index
                for expected_index, point in enumerate(expected_points)
                if _matches_semantic_point(item, point)
            ]
            if not matching_expected:
                unexpected.append(str(item.get("title") or ""))
                continue
            # If all matched expected points are themselves unmatched, this item is
            # an explicit coverage gap rather than duplicate noisy output.
            if not any(expected_index in matched_expected for expected_index in matching_expected):
                unexpected.append(str(item.get("title") or ""))
        unexpected = sorted(set(unexpected))
        results.append(
            {
                "name": str(group.get("name") or "promotion_group"),
                "session_ids": session_ids,
                "matched": matched,
                "missing": missing,
                "unexpected": unexpected,
                "passed": not missing and not unexpected,
            }
        )
    return results


def _evaluate_promotion_oracle(
    *,
    oracle: dict[str, Any],
    job_promotions: dict[str, dict[str, Any]],
    truth_lineage: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare human-reviewed expected points with all three processing stages."""

    lineage = [dict(row) for row in truth_lineage or []]
    lineage_ids = {
        str(value)
        for row in lineage
        for value in (row.get("id"), row.get("knowledge_id"))
        if str(value or "")
    }
    lineage_text = {
        (str(row.get("title") or ""), str(row.get("statement") or ""))
        for row in lineage
    }
    sessions: list[dict[str, Any]] = []
    for expected in oracle["sessions"]:
        session_id = str(expected["session_id"])
        summary = dict(job_promotions.get(session_id) or {})
        points = [dict(row) for row in summary.get("points") or []]
        packet = summary.get("answer_packet") or {}
        promoted_items = [dict(row) for row in packet.get("promoted_items") or []]
        compare_session_items = "promotions" in expected
        expected_items = [dict(row) for row in expected.get("promotions") or []]
        expected_titles = [str(row.get("title") or "") for row in expected_items]
        actual_titles = [str(row.get("title") or "") for row in promoted_items]
        expected_title_counts = Counter(expected_titles)
        actual_title_counts = Counter(actual_titles)
        missing = (
            sorted((expected_title_counts - actual_title_counts).elements())
            if compare_session_items
            else []
        )
        unexpected = (
            sorted((actual_title_counts - expected_title_counts).elements())
            if compare_session_items
            else []
        )
        statement_mismatches = []
        actual_by_title = {
            str(row.get("title") or ""): str(row.get("fact") or "")
            for row in promoted_items
        }
        for item in expected_items:
            title = str(item.get("title") or "")
            terms = [str(term).casefold() for term in item.get("statement_terms") or []]
            actual_text = actual_by_title.get(title, "").casefold()
            absent = [term for term in terms if term not in actual_text]
            if title in actual_by_title and absent:
                statement_mismatches.append({"title": title, "missing_terms": absent})
        actual_answer_counts = _count_values(points, "answer_status")
        actual_disposition_counts = _count_values(points, "disposition")
        promoted_truth_ids = {
            str(truth_id)
            for point in points
            if str(point.get("disposition") or "")
            in {"add", "refine", "confirm", "supersede"}
            for truth_id in point.get("canonical_truth_ids") or []
        }
        unresolved_truth_ids = sorted(promoted_truth_ids - lineage_ids)
        unbound_promotions = sorted(
            str(item.get("title") or "")
            for item in promoted_items
            if (
                str(item.get("title") or ""),
                str(item.get("fact") or ""),
            )
            not in lineage_text
        )
        expected_answer_counts = dict(
            sorted((expected.get("answer_status_counts") or {}).items())
        )
        expected_disposition_counts = dict(
            sorted((expected.get("disposition_counts") or {}).items())
        )
        extracted_ok = _count_matches(len(points), expected.get("point_count"))
        allowed_answers = {
            str(value) for value in expected.get("allowed_answer_statuses") or []
        }
        verified_ok = (
            actual_answer_counts == expected_answer_counts
            if "answer_status_counts" in expected
            else set(actual_answer_counts) <= allowed_answers
            and sum(actual_answer_counts.values()) == len(points)
        )
        allowed_dispositions = {
            str(value) for value in expected.get("allowed_dispositions") or []
        }
        disposition_ok = (
            actual_disposition_counts == expected_disposition_counts
            if "disposition_counts" in expected
            else set(actual_disposition_counts) <= allowed_dispositions
            and sum(actual_disposition_counts.values()) == len(points)
        )
        assimilated_ok = (
            disposition_ok
            and _count_matches(
                len(promoted_items), expected.get("promotion_count")
            )
            and not missing
            and not unexpected
            and not statement_mismatches
            and not unresolved_truth_ids
            and not unbound_promotions
        )
        sessions.append(
            {
                "session_id": session_id,
                "expected": {
                    "point_count": expected.get("point_count"),
                    "promotion_count": expected.get("promotion_count"),
                    "answer_status_counts": expected_answer_counts,
                    "disposition_counts": expected_disposition_counts,
                    "promotion_titles": expected_titles,
                },
                "extracted": {"point_count": len(points), "passed": extracted_ok},
                "verified": {
                    "answer_status_counts": actual_answer_counts,
                    "passed": verified_ok,
                },
                "assimilated": {
                    "disposition_counts": actual_disposition_counts,
                    "promotion_titles": actual_titles,
                    "unresolved_truth_ids": unresolved_truth_ids,
                    "unbound_promotions": unbound_promotions,
                    "passed": assimilated_ok,
                },
                "missing": missing,
                "unexpected": unexpected,
                "statement_mismatches": statement_mismatches,
                "passed": extracted_ok and verified_ok and assimilated_ok,
            }
        )
    group_results = _evaluate_promotion_groups(oracle, job_promotions)
    return {
        "schema_version": 1,
        "sessions": sessions,
        "promotion_groups": group_results,
        "passed": bool(sessions)
        and all(row["passed"] for row in sessions)
        and all(row["passed"] for row in group_results),
    }


def _real_state_fingerprint(
    *,
    real_data_dir: Path,
    real_notes_dir: Path,
) -> dict[str, Any]:
    return {
        "canonical_sqlite_sha256": _optional_sha256(
            canonical_store_path(real_data_dir)
        ),
        "archive_distill_sha256": _small_tree_fingerprint(
            real_data_dir / "archive_distill"
        ),
        "knowledge_workspace_sha256": _small_tree_fingerprint(
            real_data_dir / "job_workspaces" / "knowledge"
        ),
        "notes_sha256": _small_tree_fingerprint(real_notes_dir),
    }


def _quality_findings(entries: list[Any], markdown: str) -> dict[str, Any]:
    projected = project_memory_entries(entries)
    projection_keys = sorted({key for row in projected for key in row})
    headings = [
        part.strip()
        for entry in entries
        for part in list(getattr(entry, "module_path", ()) or ())
    ]
    forbidden_headings = sorted(
        {
            heading
            for heading in headings
            if heading.casefold() in _FORBIDDEN_NATURAL_HEADINGS
        }
    )
    normalized_rows = [
        (
            tuple(part.casefold().strip() for part in entry.module_path),
            entry.title.casefold().strip(),
            " ".join(entry.statement.casefold().split()),
        )
        for entry in entries
    ]
    exact_duplicates = len(normalized_rows) - len(set(normalized_rows))
    title_duplicates = sorted(
        {
            entry.title
            for entry in entries
            if sum(other.title.casefold() == entry.title.casefold() for other in entries)
            > 1
        }
    )
    leaked_markers = sorted(
        marker for marker in _FORBIDDEN_PROJECTION_MARKERS if marker in markdown
    )
    uuid_leak = bool(_UUID_PATTERN.search(markdown))
    broad_items = []
    for entry in entries:
        try:
            validate_atomic_knowledge_statement(entry.statement)
        except ValueError as error:
            broad_items.append(
                {
                    "title": entry.title,
                    "statement_length": len(entry.statement),
                    "reason": str(error),
                }
            )
    return {
        "projected_rows": projected,
        "projection_keys": projection_keys,
        "forbidden_headings": forbidden_headings,
        "leaked_markers": leaked_markers,
        "uuid_leak": uuid_leak,
        "exact_duplicate_count": exact_duplicates,
        "duplicate_titles": title_duplicates,
        "broad_item_warnings": broad_items,
        "passed": bool(
            entries
            and projection_keys == ["statement", "title"]
            and not forbidden_headings
            and not leaked_markers
            and not uuid_leak
            and exact_duplicates == 0
            and not title_duplicates
            and not broad_items
        ),
    }


async def _inspect_isolated_result(
    *,
    data_dir: Path,
    notes_dir: Path,
    project_name: str,
) -> dict[str, Any]:
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        store = backend.structured_store.knowledge_store
        entries = await store.list_entries(project_name)
        versions = await store.list_versions(project_name)
        markdown = await store.render_markdown(project_name, include_details=False)
        known_projects = await store.known_projects()
        source_counts = {
            entry.id: len(await store.list_sources(entry.id)) for entry in entries
        }
        readback = []
        for entry in entries:
            matches = await search_current_knowledge(
                backend,
                project_name=project_name,
                query=entry.title,
                limit=max(20, len(entries)),
            )
            readback.append(
                {
                    "title": entry.title,
                    "retrieved": any(match.id == entry.id for match in matches),
                }
            )
        workspace_root = store.workspace_root
        workspace_files = (
            sorted(
                path.relative_to(workspace_root).as_posix()
                for path in workspace_root.rglob("*")
                if path.is_file()
            )
            if workspace_root.exists()
            else []
        )
        jobs = backend.transcript_store.list_distill_jobs(
            project_name=project_name,
            limit=100_000,
        )
        workspace_rows: list[dict[str, Any]] = []
        for candidate in await store.list_candidates(project_name):
            evidence = await store.list_evidence(candidate.id)
            decisions = await store.list_decisions(candidate.id)
            workspace_rows.append(
                {
                    "candidate_id": candidate.id,
                    "status": candidate.status,
                    "evidence_count": len(evidence),
                    "decision_dispositions": [
                        decision.disposition for decision in decisions
                    ],
                }
            )
        workspace_expected_files = sum(
            1 + row["evidence_count"] + len(row["decision_dispositions"])
            for row in workspace_rows
        )
        workspace_policy_clean = len(workspace_files) == workspace_expected_files and all(
            row["status"] in {"deferred", "conflict"}
            and row["evidence_count"] == 1
            and row["decision_dispositions"] == [
                "defer" if row["status"] == "deferred" else "conflict"
            ]
            for row in workspace_rows
        )
        return {
            "entries": [entry.to_dict() for entry in entries],
            "entry_count": len(entries),
            "known_projects": known_projects,
            "source_counts": source_counts,
            "markdown": markdown,
            "readback": readback,
            "workspace_files": workspace_files,
            "workspace_rows": workspace_rows,
            "workspace_policy_clean": workspace_policy_clean,
            "job_statuses": {job.id: job.status for job in jobs},
            "job_sessions": {job.session_id: job.status for job in jobs},
            "job_promotions": {
                job.session_id: job.promotion_summary for job in jobs
            },
            "truth_lineage": [
                *[entry.to_dict() for entry in entries],
                *[version.to_dict() for version in versions],
            ],
            "answer_packet_sessions": sorted(
                job.session_id
                for job in jobs
                if isinstance(job.promotion_summary.get("answer_packet"), dict)
                and job.promotion_summary["answer_packet"]
            ),
            "note_sessions": sorted(
                path.stem for path in notes_dir.glob("*.md") if path.is_file()
            ),
            "canonical_sqlite": str(canonical_store_path(data_dir)),
            "quality": _quality_findings(entries, markdown),
        }
    finally:
        await backend.close()


async def _resume_retryable_cohort_jobs(
    *,
    data_dir: Path,
    notes_dir: Path,
    project_root: Path,
    session_ids: set[str],
) -> dict[str, Any]:
    """Resume only retryable jobs belonging to the frozen isolated cohort."""

    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        jobs = [
            job
            for job in backend.transcript_store.list_distill_jobs(
                project_name=project_root.name,
                limit=100_000,
            )
            if job.session_id in session_ids and job.status == "retryable"
        ]
        current = datetime.now(timezone.utc)
        blocked = [
            job
            for job in jobs
            if job.retry_after is not None and job.retry_after > current
        ]
        if blocked:
            retry_at = min(job.retry_after for job in blocked if job.retry_after)
            raise RuntimeError(f"cohort retry backoff remains active until {retry_at}")
        config = load_merged_config(project_root)
        outcomes: list[dict[str, Any]] = []
        for job in jobs:
            outcome = await asyncio.to_thread(
                run_autonomous_distill_batch,
                backend,
                project_name=project_root.name,
                project_root=project_root,
                config=config,
                trigger_id=job.session_id,
                client="codex-archive",
                notes_dir=notes_dir,
                max_jobs=1,
                preferred_job_id=job.id,
                launch_source="archive_cohort_resume",
            )
            outcomes.append(outcome)
        return {
            "state": (
                "succeeded"
                if all(outcome.get("state") == "succeeded" for outcome in outcomes)
                else "failed"
            ),
            "resumed_job_ids": [job.id for job in jobs],
            "outcomes": outcomes,
        }
    finally:
        await backend.close()


async def run_acceptance(
    *,
    project_root: Path,
    source_archive_dir: Path,
    output_root: Path,
    oracle_path: Path,
    count: int = DEFAULT_COUNT,
    resume: bool = False,
) -> dict[str, Any]:
    project_root = project_root.expanduser().resolve()
    source_archive_dir = source_archive_dir.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    oracle_path = oracle_path.expanduser().resolve()
    real_data_dir = Path.home() / ".harness-mem" / "data"
    real_notes_dir = Path.home() / ".codex" / "hm-distill" / "sessions"
    _assert_isolated_paths(
        output_root=output_root,
        source_archive_dir=source_archive_dir,
        real_data_dir=real_data_dir,
        real_notes_dir=real_notes_dir,
    )
    if count != DEFAULT_COUNT:
        raise ValueError("0.9.20 acceptance requires exactly six sessions")
    if _paths_overlap(output_root, oracle_path):
        raise ValueError("promotion oracle must be outside the acceptance output root")
    if output_root.exists() and not resume:
        raise FileExistsError(f"output root already exists: {output_root}")
    output_root.mkdir(parents=True, exist_ok=resume)
    archive_dir = output_root / "archive"
    data_dir = output_root / "data"
    notes_dir = output_root / "notes"
    manifest_path = output_root / "cohort-manifest.json"
    frozen_oracle_path = output_root / "promotion-oracle.json"
    if resume:
        manifest = _load_manifest(manifest_path, expected_count=count)
    else:
        selected = _select_project_sessions(
            project_root=project_root,
            source_archive_dir=source_archive_dir,
            count=count,
        )
        manifest = _copy_cohort(selected=selected, archive_dir=archive_dir)
        _write_json(
            manifest_path,
            {
                "schema_version": 1,
                "project_name": project_root.name,
                "project_root": str(project_root),
                "selection": "latest_first",
                "sessions": manifest,
            },
        )
    if resume:
        if not frozen_oracle_path.is_file():
            raise RuntimeError("resume requires the oracle frozen before processing")
        if _sha256(oracle_path) != _sha256(frozen_oracle_path):
            raise RuntimeError("resume oracle differs from the frozen oracle")
    else:
        shutil.copy2(oracle_path, frozen_oracle_path)
    oracle = _load_promotion_oracle(
        frozen_oracle_path,
        project_name=project_root.name,
        cohort=manifest,
    )
    oracle_sha256 = _sha256(frozen_oracle_path)
    real_before = _real_state_fingerprint(
        real_data_dir=real_data_dir,
        real_notes_dir=real_notes_dir,
    )
    started_at = datetime.now(timezone.utc)
    if resume:
        processing = await _resume_retryable_cohort_jobs(
            data_dir=data_dir,
            notes_dir=notes_dir,
            project_root=project_root,
            session_ids={str(row["session_id"]) for row in manifest},
        )
    else:
        processing = await run_archive_distill_batch(
            control_root=project_root,
            apply=True,
            archive_dir=archive_dir,
            data_dir=data_dir,
            notes_dir=notes_dir,
            verify=True,
            batch_size=count,
            daily_limit=count,
        )
    inspected = await _inspect_isolated_result(
        data_dir=data_dir,
        notes_dir=notes_dir,
        project_name=project_root.name,
    )
    original_sources_unchanged = all(
        Path(str(row["source_path"])).is_file()
        and _sha256(Path(str(row["source_path"]))) == row["source_sha256"]
        for row in manifest
    )
    isolated_sources_unchanged = all(
        Path(str(row["isolated_path"])).is_file()
        and _sha256(Path(str(row["isolated_path"]))) == row["isolated_sha256"]
        for row in manifest
    )
    real_after = _real_state_fingerprint(
        real_data_dir=real_data_dir,
        real_notes_dir=real_notes_dir,
    )
    terminal_jobs = len(inspected["job_statuses"]) == count and all(
        status == "completed" for status in inspected["job_statuses"].values()
    )
    cohort_session_ids = sorted(str(row["session_id"]) for row in manifest)
    promotion_coverage = _evaluate_promotion_oracle(
        oracle=oracle,
        job_promotions=inspected["job_promotions"],
        truth_lineage=inspected["truth_lineage"],
    )
    processing_passed = (
        processing.get("state") == "succeeded"
        if resume
        else (processing.get("verification") or {}).get("status") == "passed"
    )
    checks = {
        "exactly_six_selected": len(manifest) == count
        and len({row["session_id"] for row in manifest}) == count,
        "all_sources_are_harness_mem": all(
            row["project_name"] == project_root.name
            and Path(str(row["project_root"])).resolve() == project_root
            for row in manifest
        ),
        "cohort_completed_six": terminal_jobs
        and sorted(inspected["job_sessions"]) == cohort_session_ids,
        "latest_processing_passed": processing_passed,
        "only_harness_mem_knowledge": inspected["known_projects"]
        == [project_root.name],
        "meaningful_current_knowledge": inspected["entry_count"] > 0,
        "clean_projection": inspected["quality"]["passed"],
        "every_entry_retrievable": bool(inspected["readback"])
        and all(row["retrieved"] for row in inspected["readback"]),
        "all_jobs_terminal": terminal_jobs,
        "all_notes_materialized": inspected["note_sessions"] == cohort_session_ids,
        "all_answer_packets_persisted": inspected["answer_packet_sessions"]
        == cohort_session_ids,
        "expected_promotion_points_covered": promotion_coverage["passed"],
        "terminal_workspace_clean": inspected["workspace_policy_clean"],
        "original_archives_unchanged": original_sources_unchanged,
        "isolated_archives_retained": isolated_sources_unchanged,
        "real_runtime_state_unchanged": real_before == real_after,
    }
    report = {
        "schema_version": 1,
        "status": "passed" if all(checks.values()) else "failed",
        "project_name": project_root.name,
        "project_root": str(project_root),
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "output_root": str(output_root),
        "isolated_paths": {
            "archive": str(archive_dir),
            "data": str(data_dir),
            "notes": str(notes_dir),
            "canonical_sqlite": inspected["canonical_sqlite"],
        },
        "cohort": manifest,
        "checks": checks,
        "processing": processing,
        "knowledge": {
            key: value
            for key, value in inspected.items()
            if key not in {"markdown", "job_promotions", "truth_lineage"}
        },
        "promotion_coverage": promotion_coverage,
        "promotion_oracle": {
            "path": str(frozen_oracle_path),
            "sha256": oracle_sha256,
            "reviewed_at": oracle["reviewed_at"],
            "review_basis": oracle["review_basis"],
        },
        "real_state_before": real_before,
        "real_state_after": real_after,
        "knowledge_markdown": str(output_root / "knowledge.md"),
    }
    (output_root / "knowledge.md").write_text(
        inspected["markdown"], encoding="utf-8"
    )
    _write_json(output_root / "report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--source-archive-dir",
        type=Path,
        default=Path.home() / ".codex" / "archived_sessions",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--oracle",
        type=Path,
        required=True,
        help="Human-reviewed expected promotion points for the frozen cohort.",
    )
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    report = asyncio.run(
        run_acceptance(
            project_root=args.project_root,
            source_archive_dir=args.source_archive_dir,
            output_root=args.output_root,
            oracle_path=args.oracle,
            count=args.count,
            resume=args.resume,
        )
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_COUNT",
    "_assert_isolated_paths",
    "_quality_findings",
    "_evaluate_promotion_oracle",
    "_load_promotion_oracle",
    "_select_project_sessions",
    "run_acceptance",
]
