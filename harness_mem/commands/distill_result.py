"""Readable organization results projected from current knowledge, never drafts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from harness_mem.core.schemas.session_distill import SessionDistillJob


_NO_WRITE_REASONS = {
    "confirm": "已有相同知识",
    "no_write": "没有需要新增的长期知识",
    "reject": "证据或长期价值不足",
    "handoff": "保留为未完成事项",
    "defer": "暂缓处理",
    "conflict": "存在待解决冲突",
}


def distill_unfinished_work(job: SessionDistillJob) -> list[str]:
    """Merge the Agent's work list with the job's persisted handoff projection."""
    promotion = job.promotion_summary or {}
    items = [
        str(item).strip()
        for item in [*(job.semantic_review.get("unfinished_work") or []),
                     *(promotion.get("unfinished_work") or [])]
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
    elif packet.get("answer_status") == "ANSWERED" and not promotion.get("promoted"):
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
    return {
        "organization_status": "partial" if no_write.get("暂缓处理") or no_write.get("存在待解决冲突") else "completed",
        "knowledge_changes": sorted(
            changes.values(), key=lambda row: (tuple(row["module"]), row["title"])
        ),
        "removed_count": len(removed),
        "not_written": [
            {"reason": reason, "count": count}
            for reason, count in sorted(no_write.items())
        ],
        "unfinished_work": list(dict.fromkeys(unfinished_work)),
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
