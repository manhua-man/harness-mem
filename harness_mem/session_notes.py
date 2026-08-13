"""Job-bound, user-readable Session Note materialization."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from harness_mem.core.schemas.session_distill import SessionDistillJob


_COMPLETED_MARKER = re.compile(r"completed=([^ ]+)")
UNRECOVERABLE_SESSION_SUMMARY = (
    "The session topic could not be recovered from the available evidence."
)


def is_meaningful_session_summary(value: Any) -> bool:
    """Reject empty, underspecified, and renderer-generated summary placeholders."""

    summary = " ".join(str(value or "").split())
    return len(summary) >= 12 and summary != UNRECOVERABLE_SESSION_SUMMARY


def session_note_path(notes_dir: Path, job: SessionDistillJob) -> Path:
    """Return the immutable Note path for one distill job/revision."""

    if not str(job.session_id).strip():
        raise ValueError("session note path requires a non-empty session identity")
    return notes_dir / "revisions" / job.id / f"{job.session_id}.md"


def existing_session_note_path(
    notes_dir: Path,
    job: SessionDistillJob,
) -> tuple[Path | None, str | None]:
    """Resolve one existing immutable Note, including pruned historical jobs."""

    session_id = str(job.session_id or "").strip()
    if session_id:
        expected = notes_dir / "revisions" / job.id / f"{session_id}.md"
        if expected.is_file():
            return expected, session_id
    revision_dir = notes_dir / "revisions" / job.id
    try:
        candidates = [
            path
            for path in revision_dir.glob("*.md")
            if path.is_file()
            and path.name != ".md"
            and not path.name.startswith(".")
            and path.stem.strip()
        ]
    except OSError:
        return None, None
    if len(candidates) != 1:
        return None, None
    return candidates[0], candidates[0].stem


def latest_session_note_path(notes_dir: Path, session_id: str) -> Path:
    """Return the convenient latest-Note path for a user-facing session id."""

    return notes_dir / f"{session_id}.md"


def materialize_session_note(
    job: SessionDistillJob,
    *,
    notes_dir: Path,
) -> dict[str, Any]:
    """Write an immutable job Note and advance the session's latest view safely."""

    content = render_session_note(job)
    immutable_path = session_note_path(notes_dir, job)
    _atomic_write(immutable_path, content)

    latest_path = latest_session_note_path(notes_dir, job.session_id)
    if _should_advance_latest(latest_path, job.completed_at):
        _atomic_write(latest_path, content)

    return {
        "path": str(immutable_path),
        "latest_path": str(latest_path),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "chars": len(content),
        "exists": immutable_path.is_file(),
        "meaningful": len(content.strip()) >= 200 and job.session_id in content,
        "job_binding_valid": job.id in content,
        "materialized_at": _now(),
    }


def render_session_note(job: SessionDistillJob) -> str:
    review = dict(job.semantic_review or {})
    summary = str(
        review.get("session_summary") or review.get("final_user_request") or ""
    ).strip()
    outcome = str(
        review.get("final_outcome") or "No final outcome was recorded."
    ).strip()
    unfinished = [
        str(item).strip()
        for item in review.get("unfinished_work", [])
        if str(item).strip()
    ]
    promotion = dict(job.promotion_summary or {})
    packet = dict(promotion.get("answer_packet") or {})
    completed = job.completed_at or datetime.now(timezone.utc)
    completed_iso = completed.isoformat()
    lines = [
        f"# {summary[:80] or 'Session Note'}",
        "",
        "> 历史会话 Note：用于说明这次会话做了什么，不代表当前项目真相。",
        "",
        "## 会话主题",
        "",
        summary or UNRECOVERABLE_SESSION_SUMMARY,
        "",
        "## 最终结果",
        "",
        outcome,
        "",
        "## 未完成工作",
        "",
    ]
    lines.extend(f"- {item}" for item in unfinished)
    if not unfinished:
        lines.append("- 无。")
    lines.extend(
        [
            "",
            "## 记忆治理结果",
            "",
            f"- 结果：{job.completion_disposition or 'unknown'}",
            f"- 形成长期记忆：{int(promotion.get('promoted') or 0)} 条",
            "",
            "## Answer Packet",
            "",
            f"- 验证问题：{packet.get('question') or '未记录。'}",
            f"- 验证状态：{packet.get('answer_status') or 'UNANSWERED'}",
            f"- 核心结论：{packet.get('core_conclusion') or '未形成可验证结论。'}",
            f"- 证据基础：{', '.join(packet.get('evidence_basis') or []) or '无'}",
            f"- 验证时间：{packet.get('verified_at') or '无'}",
            f"- 晋升状态：{packet.get('promotion_status') or 'not_promoted'}",
            f"- 目标项目：{packet.get('destination_project') or job.project_name}",
            f"- 知识类型：{', '.join(packet.get('knowledge_kind') or []) or '无'}",
            f"- 知识分类：{', '.join(packet.get('knowledge_category') or []) or '无'}",
            "",
            "### 晋升内容",
            "",
            "",
            (
                "<!-- harness-mem audit: "
                f"session={job.session_id} job={job.id} completed={completed_iso} "
                f"disposition={job.completion_disposition or 'unknown'} -->"
            ),
            "",
        ]
    )
    promoted_items = list(packet.get("promoted_items") or [])
    insertion = len(lines) - 2
    rendered_items = [
        (
            f"- **{item.get('title') or item.get('category') or '长期知识'}**："
            f"{item.get('fact') or ''}（{item.get('kind') or 'knowledge'} / "
            f"{item.get('category') or 'uncategorized'}）"
        )
        for item in promoted_items
    ] or ["- 无。"]
    lines[insertion:insertion] = rendered_items + [""]
    return "\n".join(lines)


def _should_advance_latest(path: Path, completed_at: datetime | None) -> bool:
    if not path.is_file():
        return True
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError:
        return True
    match = _COMPLETED_MARKER.search(existing)
    if match is None:
        return True
    try:
        prior = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
    except ValueError:
        return True
    current = completed_at or datetime.now(timezone.utc)
    if prior.tzinfo is None:
        prior = prior.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current >= prior


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "existing_session_note_path",
    "latest_session_note_path",
    "materialize_session_note",
    "render_session_note",
    "session_note_path",
]
