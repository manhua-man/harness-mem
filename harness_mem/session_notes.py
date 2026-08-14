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

_ANSWER_STATUS_LABELS = {
    "ANSWERED": "已验证",
    "PARTIAL": "证据不完整",
    "UNANSWERED": "没有充分证据",
    "CONTRADICTED": "证据冲突",
    "STALE": "证据已过期",
    "NOT_APPLICABLE": "不涉及长期记忆",
}
_PROMOTION_STATUS_LABELS = {
    "promoted": "已写入长期记忆",
    "partial": "部分写入长期记忆",
    "not_promoted": "未写入长期记忆",
}
_COMPLETION_LABELS = {
    "promoted": "形成长期记忆",
    "no_candidate": "无需长期记忆",
}
_EVIDENCE_BASIS_LABELS = {
    "repository": "当前项目文件",
    "user_statement": "用户明确表达",
    "transcript": "会话内容",
}
_USER_VISIBLE_REPLACEMENTS = (
    (re.compile(r"\bjob_bound_truth\b", re.IGNORECASE), "按原处理记录回查"),
    (
        re.compile(r"\bsanitized_project_truth\b", re.IGNORECASE),
        "清理原文后按项目记忆回查",
    ),
    (re.compile(r"\bsemantic memor(?:y|ies)\b", re.IGNORECASE), "长期记忆"),
    (re.compile(r"\boutcome contract\b", re.IGNORECASE), "结果验收"),
    (re.compile(r"\bstop hook\b", re.IGNORECASE), "会话结束自动触发流程"),
    (re.compile(r"\bhook\b", re.IGNORECASE), "自动触发流程"),
    (re.compile(r"\banswer packet\b", re.IGNORECASE), "结果校验"),
    (re.compile(r"\bpromoted_items\b", re.IGNORECASE), "写入的长期记忆列表"),
    (re.compile(r"\bwake/search_memory\b", re.IGNORECASE), "继续任务和记忆检索"),
    (re.compile(r"\brelation\b", re.IGNORECASE), "关系记忆"),
    (re.compile(r"\btruth\b", re.IGNORECASE), "长期记忆"),
    (re.compile(r"\bcandidate\b", re.IGNORECASE), "待审记忆"),
    (re.compile(r"\bfail-closed\b", re.IGNORECASE), "安全性不明时停止操作"),
    (re.compile(r"\bnote\b", re.IGNORECASE), "会话摘要"),
    (re.compile("长期知识"), "长期记忆"),
    (re.compile("可读真值"), "可读长期记忆"),
    (re.compile("真值"), "长期记忆"),
)


def _readable_label(value: Any, labels: dict[str, str], fallback: str) -> str:
    return labels.get(str(value or ""), fallback)


def _readable_evidence_basis(values: Any) -> str:
    labels = [
        _EVIDENCE_BASIS_LABELS.get(str(value), str(value))
        for value in (values or [])
        if str(value).strip()
    ]
    return "、".join(labels) or "无"


def _user_visible_text(value: Any) -> str:
    """Translate known storage and audit jargon at the Note boundary."""

    text = str(value or "").strip()
    if re.search(r"[\u4e00-\u9fff]", text) is None:
        return text
    for pattern, replacement in _USER_VISIBLE_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)


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
    summary = _user_visible_text(
        review.get("session_summary") or review.get("final_user_request") or ""
    )
    outcome = _user_visible_text(
        review.get("final_outcome") or "No final outcome was recorded."
    )
    unfinished = [
        _user_visible_text(item)
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
        "> 历史会话记录（Note）：用于说明这次会话做了什么，不代表当前项目真相。",
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
            "- 结果："
            + _readable_label(
                job.completion_disposition,
                _COMPLETION_LABELS,
                "状态未知",
            ),
            f"- 形成长期记忆：{int(promotion.get('promoted') or 0)} 条",
            "",
            "## Answer Packet（结果校验）",
            "",
            f"- 验证问题：{_user_visible_text(packet.get('question') or '未记录。')}",
            "- 验证状态："
            + _readable_label(
                packet.get("answer_status"),
                _ANSWER_STATUS_LABELS,
                "没有充分证据",
            ),
            "- 核心结论："
            + _user_visible_text(
                packet.get("core_conclusion") or "未形成可验证结论。"
            ),
            f"- 证据来源：{_readable_evidence_basis(packet.get('evidence_basis'))}",
            f"- 验证时间：{packet.get('verified_at') or '无'}",
            "- 写入状态："
            + _readable_label(
                packet.get("promotion_status"),
                _PROMOTION_STATUS_LABELS,
                "未写入长期记忆",
            ),
            f"- 记忆归属项目：{packet.get('destination_project') or job.project_name}",
            "",
            "### 写入的长期记忆",
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
            f"- **{item.get('title') or '长期记忆'}**："
            f"{item.get('fact') or ''}"
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
