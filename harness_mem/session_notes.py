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


def session_note_path(notes_dir: Path, job: SessionDistillJob) -> Path:
    """Return the immutable Note path for one distill job/revision."""

    return notes_dir / "revisions" / job.id / f"{job.session_id}.md"


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
    completed = job.completed_at or datetime.now(timezone.utc)
    completed_iso = completed.isoformat()
    lines = [
        f"# {summary[:80] or 'Session Note'}",
        "",
        "> 历史会话 Note：用于说明这次会话做了什么，不代表当前项目真相。",
        "",
        "## 会话主题",
        "",
        summary or "The session topic could not be recovered from the available evidence.",
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
            (
                "<!-- harness-mem audit: "
                f"session={job.session_id} job={job.id} completed={completed_iso} "
                f"disposition={job.completion_disposition or 'unknown'} -->"
            ),
            "",
        ]
    )
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
    "latest_session_note_path",
    "materialize_session_note",
    "render_session_note",
    "session_note_path",
]
