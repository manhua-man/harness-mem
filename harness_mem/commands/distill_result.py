"""Readable organization results projected from current knowledge, never drafts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from harness_mem.core.schemas.session_distill import RetainedStateRef, SessionDistillJob


_NO_WRITE_REASONS = {
    "confirm": "已有相同知识",
    "no_write": "没有需要新增的长期知识",
    "reject": "证据或长期价值不足",
    "handoff": "保留为未完成事项",
    "defer": "暂缓处理",
    "conflict": "存在待解决冲突",
}


def _retained_state_items(job: SessionDistillJob) -> set[str]:
    """Use explicit semantic bindings only after their point has been saved.

    Finalization owns validation of the state classification and source binding.
    This projection never infers state/action meaning from the item's wording.
    """
    if (getattr(job, "status", None) != "completed"
            or job.promotion_summary.get("readback", {}).get("verified") is not True):
        return set()
    points: dict[str, list[Mapping[str, Any]]] = {}
    for point in job.promotion_summary.get("points") or []:
        if isinstance(point, Mapping):
            points.setdefault(str(point.get("candidate_id") or ""), []).append(point)
    retained: set[str] = set()
    for raw in job.semantic_review.get("retained_state_refs") or []:
        try:
            ref = RetainedStateRef.model_validate(raw)
        except (TypeError, ValueError):
            continue
        candidate_points = points.get(ref.candidate_id) or []
        if candidate_points and all(
            point.get("answer_status") == "ANSWERED"
            and point.get("disposition") in {"add", "confirm", "refine", "replace"}
            and isinstance(point.get("canonical_truth_ids"), list)
            and point["canonical_truth_ids"]
            and all(isinstance(value, str) and value.strip() for value in point["canonical_truth_ids"])
            and not point.get("handoff_id")
            for point in candidate_points
        ):
            retained.add(ref.unfinished_work_item)
    return retained


def distill_unfinished_work(job: SessionDistillJob) -> list[str]:
    """Keep task work separate from explicitly bound, successfully saved states."""
    promotion = job.promotion_summary or {}
    retained = _retained_state_items(job)
    review_work = [
        item for item in job.semantic_review.get("unfinished_work") or []
        if str(item).strip() not in retained
    ]
    items = [
        str(item).strip()
        for item in [*review_work, *(promotion.get("unfinished_work") or [])]
        if str(item).strip()
    ]
    if not items and (
        promotion.get("readback", {}).get("handoff_ids")
        or any(point.get("disposition") in {"defer", "handoff", "conflict"}
               for point in promotion.get("points") or [])
    ):
        question = (promotion.get("answer_packet") or {}).get("question")
        items.append("继续处理：" + str(question or "待验证的会话内容"))
    return list(dict.fromkeys(items))


def distill_display_review(job: SessionDistillJob) -> dict[str, Any]:
    """Never let Agent self-reported success override the runtime evidence gate."""
    review = dict(job.semantic_review or {})
    promotion = job.promotion_summary or {}
    packet = promotion.get("answer_packet") or {}
    unfinished = distill_unfinished_work(job)
    review["unfinished_work"] = unfinished
    blocked = packet.get("answer_status") in {"PARTIAL", "UNANSWERED", "CONTRADICTED", "STALE"}
    unresolved = job.completion_disposition in {"deferred", "handoff", "conflict"} or any(
        point.get("disposition") in {"defer", "handoff", "conflict"}
        for point in promotion.get("points") or []
    )
    if blocked or unresolved:
        outcome = (
            str(packet.get("core_conclusion") or "整理尚未完成，本次未写入长期记忆。")
            if blocked or promotion.get("promoted")
            else "本次内容保留为待处理事项，未写入长期记忆。"
        )
        if unfinished:
            outcome += " 仍有待处理事项。"
        review["final_outcome"] = outcome
        review["evidence_status"] = "partial"
        review["last_turn_status"] = "unfinished" if unfinished else "unknown"
    elif packet.get("answer_status") in {"ANSWERED", "NOT_APPLICABLE"} and not promotion.get("promoted"):
        review["final_outcome"] = "本次未新增或替换长期记忆。"
    return review


def project_distill_result(
    points: Iterable[Mapping[str, Any]],
    entries: Mapping[str, Mapping[str, Any]],
    *,
    empty_reasons: Iterable[str] = (),
    unfinished_work: Iterable[str] = (),
) -> dict[str, Any]:
    """Use one current snapshot for single-session and batch result prose.

    Replaced entries absent from this snapshot are not reported as new changes.
    Internal identities are used for deduplication only and never returned.
    """
    changes: dict[str, dict[str, Any]] = {}
    removed: set[str] = set()
    no_write: Counter[str] = Counter(empty_reasons)
    for point in points:
        disposition = str(point.get("disposition") or "")
        if disposition in {"add", "refine", "replace"}:
            for entry_id in point.get("canonical_truth_ids") or []:
                entry = entries.get(entry_id)
                if entry is None:
                    continue
                changes[entry_id] = {
                    "change": "added" if disposition == "add" else "replaced",
                    "module": list(entry.get("module_path") or []),
                    "title": str(entry["title"]),
                    "statement": str(entry["statement"]),
                }
            removed.update(point.get("replaced_truth_ids") or [])
        else:
            no_write[_NO_WRITE_REASONS.get(disposition, "未写入")] += 1
    unfinished = list(dict.fromkeys(unfinished_work))
    unresolved = bool(
        unfinished or no_write.get("暂缓处理") or no_write.get("存在待解决冲突")
        or no_write.get("保留为未完成事项")
    )
    return {
        "organization_status": "partial" if unresolved else "completed",
        "knowledge_changes": sorted(
            changes.values(), key=lambda row: (tuple(row["module"]), row["title"])
        ),
        "removed_count": len(removed),
        "not_written": [
            {"reason": reason, "count": count}
            for reason, count in sorted(no_write.items())
        ],
        "unfinished_work": unfinished,
    }


async def current_distill_result(backend: Any, job: SessionDistillJob) -> dict[str, Any]:
    """Called only after verified completion, including its idempotent replay."""
    entries = {
        entry.id: entry.to_dict()
        for entry in await backend.structured_store.knowledge_store.list_entries(
            job.project_name
        )
    }
    points = job.promotion_summary.get("points") or []
    for point in points:
        if point.get("disposition") not in {"add", "refine", "replace"}:
            continue
        ids = point.get("canonical_truth_ids") or []
        if not ids or any(entry_id not in entries for entry_id in ids):
            raise ValueError("completion result is missing current knowledge")
        if any(entry_id in entries for entry_id in point.get("replaced_truth_ids") or []):
            raise ValueError("completion result still contains replaced knowledge")
    reason = (
        "保留为未完成事项"
        if job.promotion_summary.get("readback", {}).get("handoff_ids")
        else "没有需要长期记住的内容"
    )
    return project_distill_result(
        points, entries, empty_reasons=[reason] if not points else (),
        unfinished_work=distill_unfinished_work(job),
    )
