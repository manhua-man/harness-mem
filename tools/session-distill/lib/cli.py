#!/usr/bin/env python3
"""Session Distiller maintenance CLI.

This CLI is the scriptable implementation layer for the `/hm:*` slash commands.
The user-facing product path remains Slash/MCP/Skill; this file keeps local
maintenance deterministic and testable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

# Allow importing vendored parser from lib/parser.py.
_SKILL_ROOT = Path(__file__).resolve().parent.parent
_LIB_DIR = _SKILL_ROOT / "lib"
if _LIB_DIR.exists():
    sys.path.insert(0, str(_SKILL_ROOT))

from lib.parser import (  # type: ignore[import-untyped]  # noqa: E402  # isort:skip
    list_session_files,
    parse_claude_jsonl_session,
)
from lib.guardrails import contains_pending_draft, raw_deletion_root  # noqa: E402
from lib.models import KnowledgeEntry  # noqa: E402
from lib.packet import (  # noqa: E402
    packet_audit_from_jsonl_file,
    render_session_packet_markdown,
)


def _default_distill_dir() -> Path:
    env_dir = os.environ.get("SESSION_DISTILL_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".codex" / "session-distill"


# Configuration
DISTILL_DIR = _default_distill_dir()
MANIFEST_FILE = DISTILL_DIR / "manifest.json"
KNOWLEDGE_FILE = DISTILL_DIR / "knowledge-base.md"
PACKETS_DIR = DISTILL_DIR / "packets"
DISTILLED_DIR = DISTILL_DIR / "distilled" / "sessions"
MEMORY_DRAFTS_DIR = DISTILL_DIR / "memory-drafts"
KB_BACKUPS_DIR = DISTILL_DIR / "backups" / "knowledge-base"
KB_REVIEW_STATE_FILE = DISTILL_DIR / "kb-review-state.json"
PRUNED_SOURCES_FILE = DISTILL_DIR / "pruned-sources.jsonl"

PROJECTS_DIR = Path(os.environ.get("SESSION_DISTILL_PROJECTS_DIR", Path.home() / ".claude" / "projects"))

# PRD sync configuration
PRD_DISTILLED_DIR = DISTILL_DIR / "prd-distilled"
DEFAULT_RUN_NEXT = 3
DEFAULT_LIST_MIN_SIZE_KB = 100
KB_REVIEW_REMINDER_THRESHOLD = 5
VERIFY_REMINDER_LIMIT = 5
KEYWORD_STOPWORDS = {
    "assistant",
    "content",
    "distilled",
    "distillation",
    "evidence",
    "final",
    "knowledge",
    "metadata",
    "packet",
    "project",
    "request",
    "response",
    "review",
    "session",
    "source",
    "summary",
    "tools",
    "transcript",
    "turn",
    "user",
}
REQUIRED_NOTE_SECTIONS = (
    "Source",
    "Raw Review",
    "Summary",
    "Verification From Session",
    "Promotion Decision",
)
HANDLED_MANIFEST_STATUSES = frozenset({"distilled", "skipped"})
KNOWLEDGE_REVIEW_STATUSES = ("stable", "needs-review", "stale", "superseded")
PRUNABLE_KB_STATUSES = frozenset({"stale", "superseded"})
CODEX_RAW_ROOTS = (
    Path.home() / ".codex" / "archived_sessions",
    Path.home() / ".codex" / "sessions",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def ensure_dirs() -> None:
    """Create necessary directories."""
    DISTILL_DIR.mkdir(parents=True, exist_ok=True)
    PACKETS_DIR.mkdir(parents=True, exist_ok=True)
    DISTILLED_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    KB_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    if not KNOWLEDGE_FILE.exists():
        KNOWLEDGE_FILE.write_text("# Session Distill Knowledge Base\n", encoding="utf-8")

    if not MANIFEST_FILE.exists():
        save_manifest({"version": 1, "updated_at": "", "sessions": []})


def load_manifest() -> dict[str, Any]:
    """Load manifest file."""
    if MANIFEST_FILE.exists():
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    return {"version": 1, "updated_at": "", "sessions": []}


def save_manifest(manifest: dict[str, Any]) -> None:
    """Save manifest file."""
    manifest["updated_at"] = utc_now()
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def find_project_path(project_name: Optional[str] = None) -> Optional[Path]:
    """Find project directory."""
    if not project_name:
        project_name = Path.cwd().name

    project_path = PROJECTS_DIR / project_name
    if project_path.exists():
        return project_path
    return None


def source_signature(session: dict[str, Any]) -> dict[str, Any]:
    """Return a comparable signature for a session file."""
    path = Path(session["path"])
    stat = path.stat()
    return {
        "file_path": str(path),
        "file_size_bytes": stat.st_size,
        "source_mtime": stat.st_mtime,
        "size": f"{stat.st_size / 1024:.1f}KB",
        "last_seen_at": utc_now(),
        "source_missing": False,
    }


def cmd_index(project_path: Optional[Path]) -> int:
    """Index sessions."""
    print("==> Index: Scanning sessions")
    ensure_dirs()
    manifest = load_manifest()
    new_count = 0
    refreshed_count = 0

    sessions = list_session_files(project_path, min_size_kb=0) if project_path else []
    existing_by_id = {s["session_id"]: s for s in manifest["sessions"]}

    for session in sessions:
        session_id = session["name"].replace(".jsonl", "")
        signature = source_signature(session)
        existing = existing_by_id.get(session_id)

        if not existing:
            print(f"  + {session['name']} ({session['size']})")
            manifest["sessions"].append(
                {
                    "session_id": session_id,
                    "file_name": session["name"],
                    **signature,
                    "status": "new",
                    "bundle_path": None,
                    "distilled_path": None,
                    "notes": "",
                }
            )
            new_count += 1
            continue

        changed = (
            existing.get("file_path") != signature["file_path"]
            or existing.get("file_size_bytes") != signature["file_size_bytes"]
            or existing.get("source_mtime") != signature["source_mtime"]
        )

        existing.update(
            {
                "file_name": session["name"],
                "size": signature["size"],
                "file_path": signature["file_path"],
                "file_size_bytes": signature["file_size_bytes"],
                "source_mtime": signature["source_mtime"],
                "last_seen_at": signature["last_seen_at"],
                "source_missing": False,
            }
        )

        if changed:
            existing["status"] = "new"
            existing["bundle_path"] = None
            existing["distilled_path"] = None
            refreshed_count += 1
            print(f"  ~ Refreshed: {session['name']} ({session['size']})")

    save_manifest(manifest)
    print(f"==> Index done: {new_count} new sessions, {refreshed_count} refreshed")
    return 0


def pending_sessions(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return bundle candidates sorted by freshest source first."""
    candidates = [s for s in manifest["sessions"] if s["status"] in ["new", "bundled"]]
    return sorted(candidates, key=lambda s: s.get("source_mtime", 0), reverse=True)


def cmd_bundle(
    project_path: Optional[Path],
    force: bool = False,
    next_count: int = DEFAULT_RUN_NEXT,
) -> int:
    """Generate packets."""
    print("==> Bundle: Generating packets")
    ensure_dirs()
    manifest = load_manifest()
    count = 0

    target_count = next_count if next_count is not None and next_count > 0 else None

    for session in pending_sessions(manifest):
        if target_count is not None and count >= target_count:
            break

        session_id = session["session_id"]
        packet_path = PACKETS_DIR / f"{session_id}.md"

        if session["status"] == "bundled" and packet_path.exists() and not force:
            print(f"  -> Already bundled: {session_id}")
            continue

        print(f"  -> Generating: {session_id}")
        generate_packet(session, packet_path)
        maybe_print_verify_entry_reminder(
            session_id,
            packet_path.read_text(encoding="utf-8", errors="replace"),
            trigger="packet",
        )
        session["status"] = "bundled"
        session["bundle_path"] = str(packet_path)
        count += 1

    save_manifest(manifest)
    print(f"==> Bundle done: {count} packets")
    return 0


def generate_packet(session: dict[str, Any], packet_path: Path) -> None:
    """Generate a packet file with actual session content."""
    session_path = Path(session["file_path"])
    audit = packet_audit_from_jsonl_file(session_path)
    turns = parse_claude_jsonl_session(
        session_path,
        filter_xml_directives=True,
        on_error="warn",
    )
    packet_path.write_text(
        render_session_packet_markdown(session, audit, turns),
        encoding="utf-8",
    )


def cmd_status(project_path: Optional[Path]) -> int:
    """Show status."""
    print("==> Session Distiller Status")
    print("")

    if not MANIFEST_FILE.exists():
        print("No sessions recorded yet")
        return 0

    manifest = load_manifest()
    total = len(manifest["sessions"])
    new = sum(1 for s in manifest["sessions"] if s["status"] == "new")
    bundled = sum(1 for s in manifest["sessions"] if s["status"] == "bundled")
    distilled = sum(1 for s in manifest["sessions"] if s["status"] == "distilled")
    skipped = sum(1 for s in manifest["sessions"] if s["status"] == "skipped")
    source_missing = sum(1 for s in manifest["sessions"] if s.get("source_missing"))

    print(
        "Sessions: "
        f"{total} total | new={new} | bundled={bundled} | "
        f"distilled={distilled} | skipped={skipped} | source_missing={source_missing}"
    )
    print("")

    if bundled > 0:
        print("Pending packets:")
        for session in manifest["sessions"]:
            if session["status"] == "bundled":
                print(f"  - {session['session_id']}")
        print("")

    kb_lines = len(KNOWLEDGE_FILE.read_text(encoding="utf-8").splitlines()) if KNOWLEDGE_FILE.exists() else 0
    print(f"Knowledge base: {KNOWLEDGE_FILE} ({kb_lines} lines)")
    return 0


def cmd_list(project_path: Optional[Path], min_size: int = 100) -> int:
    """List available sessions."""
    print("==> Available Sessions")
    print("")

    sessions = list_session_files(project_path, min_size_kb=min_size) if project_path else []
    if not sessions:
        print(f"No sessions found larger than {min_size}KB")
        return 0

    print(f"{'Size':<8} {'Lines':<6} {'Modified':<12} Filename")
    print("-" * 60)
    for session in sessions:
        if hasattr(session["mtime"], "strftime"):
            mtime_str = session["mtime"].strftime("%Y-%m-%d")
        else:
            mtime_str = str(session["mtime"])
        print(f"{session['size']:<8} {session['lines']:<6} {mtime_str:<12} {session['name']}")
    return 0


def find_manifest_session(manifest: dict[str, Any], session_id: str) -> Optional[dict[str, Any]]:
    for session in manifest["sessions"]:
        if session["session_id"] == session_id:
            return session
    return None


def note_path_for(session_id: str, session: Optional[dict[str, Any]] = None) -> Path:
    if session and session.get("distilled_path"):
        return Path(session["distilled_path"])
    return DISTILLED_DIR / f"{session_id}.md"


def bundle_path_for(session_id: str, session: Optional[dict[str, Any]] = None) -> Path:
    if session and session.get("bundle_path"):
        return Path(session["bundle_path"])
    return PACKETS_DIR / f"{session_id}.md"


def section_text(markdown: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(markdown)
    if not match:
        return ""
    rest = markdown[match.end() :]
    next_heading = re.search(r"^##\s+", rest, flags=re.MULTILINE)
    return rest[: next_heading.start()] if next_heading else rest


def packet_is_partial(session_id: str, session: Optional[dict[str, Any]] = None) -> bool:
    packet_path = bundle_path_for(session_id, session)
    if not packet_path.exists():
        return False
    packet_text = packet_path.read_text(encoding="utf-8", errors="replace").lower()
    return "coverage: `partial`" in packet_text or "coverage: partial" in packet_text


def validate_session_note(session_id: str, session: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    note_path = note_path_for(session_id, session)
    if not note_path.exists():
        return [f"session note missing: {note_path}"]

    note = note_path.read_text(encoding="utf-8", errors="replace")
    for heading in REQUIRED_NOTE_SECTIONS:
        if not section_text(note, heading).strip():
            errors.append(f"missing or empty section: {heading}")

    if packet_is_partial(session_id, session):
        raw_review = section_text(note, "Raw Review")
        if not re.search(r"raw (?:transcript )?reviewed\s*:\s*yes", raw_review, re.IGNORECASE):
            errors.append("partial packet requires Raw Review to say `Raw transcript reviewed: yes`")

    promotion = section_text(note, "Promotion Decision")
    if re.search(r"\b(todo|pending|tbd|fill in)\b", promotion, re.IGNORECASE):
        errors.append("Promotion Decision still contains placeholder/pending text")
    if not re.search(r"\b(promote|no promotion)\b\s*:", promotion, re.IGNORECASE):
        errors.append("Promotion Decision must include `Promote:` or `No Promotion:`")

    return errors


def draft_has_pending(session_id: str) -> tuple[bool, Optional[Path]]:
    draft_path = MEMORY_DRAFTS_DIR / f"{session_id}.json"
    if not draft_path.exists():
        return False, None
    try:
        payload = json.loads(draft_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True, draft_path

    return contains_pending_draft(payload), draft_path


def append_pruned_source(record: dict[str, Any]) -> None:
    PRUNED_SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PRUNED_SOURCES_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def maybe_delete_raw_source(session: dict[str, Any], keep_raw: bool) -> None:
    if keep_raw:
        session["raw_retained_reason"] = "keep_raw"
        return

    file_path = session.get("file_path")
    if not file_path:
        session["source_missing"] = True
        return

    raw_path = Path(file_path)
    if not raw_path.exists():
        session["source_missing"] = True
        session.setdefault("raw_missing_seen_at", utc_now())
        return

    allowed_root = raw_deletion_root(raw_path, CODEX_RAW_ROOTS)
    if allowed_root is None:
        session["raw_retained_reason"] = "outside_codex_raw_roots"
        return

    stat = raw_path.stat()
    append_pruned_source(
        {
            "session_id": session["session_id"],
            "path": str(raw_path),
            "bytes": stat.st_size,
            "deleted_at": utc_now(),
            "allowed_root": str(allowed_root),
        }
    )
    raw_path.unlink()
    session["source_missing"] = True
    session["raw_deleted_at"] = utc_now()


def validate_same_source_kb(session_id: str) -> list[str]:
    errors: list[str] = []
    entries = parse_knowledge_entries()
    for entry in entries:
        if entry.source_session_id == session_id and entry.status != "stable":
            errors.append(
                f"knowledge-base line {entry.line_no} for same source is {entry.status}: "
                + "; ".join(entry.reasons)
            )
    return errors


def validate_distilled_guardrails(session_id: str, session: dict[str, Any]) -> list[str]:
    """Return the closure guardrail failures for `/hm:mark ... distilled`.

    v2.8 formalizes `distilled` as the explicit session-closure state. A
    session cannot be marked `distilled` unless all note/draft/knowledge
    guardrails are already satisfied. Keeping the checks in one helper makes
    the contract easier to test and harder to drift.
    """
    errors = []
    errors.extend(validate_session_note(session_id, session))
    pending, draft_path = draft_has_pending(session_id)
    if pending:
        errors.append(f"memory draft still has pending entries: {draft_path}")
    errors.extend(validate_same_source_kb(session_id))
    return errors


def cmd_mark(session_id: str, status: str, keep_raw: bool = False) -> int:
    """Mark session status after running guardrails for distilled sessions."""
    if not session_id or not status:
        print("Usage: session-distill mark SESSION-ID STATUS")
        return 1

    ensure_dirs()
    print("==> Mark: Updating status")
    manifest = load_manifest()
    session = find_manifest_session(manifest, session_id)
    if not session:
        print(f"  ! Session not found: {session_id}")
        return 1

    if status == "distilled":
        errors = validate_distilled_guardrails(session_id, session)
        if errors:
            print("  ! Mark refused by guardrails:")
            for error in errors:
                print(f"    - {error}")
            return 1

        session["distilled_path"] = str(note_path_for(session_id, session))
        maybe_delete_raw_source(session, keep_raw)

    session["status"] = status
    session["marked_at"] = utc_now()
    save_manifest(manifest)
    print(f"  -> {session_id} -> {status}")
    if status == "distilled" and session.get("source_missing"):
        print("  -> raw source marked missing/deleted; manifest keeps distilled state")
    elif status == "distilled" and session.get("raw_retained_reason"):
        print(f"  -> raw source retained: {session['raw_retained_reason']}")
    if status == "distilled":
        note_path = note_path_for(session_id, session)
        if note_path.exists():
            maybe_print_verify_entry_reminder(
                session_id,
                note_path.read_text(encoding="utf-8", errors="replace"),
                trigger="session note",
            )
        maybe_print_kb_review_reminder()
    print("==> Mark done")
    return 0


def parse_statuses(statuses_text: Optional[str]) -> set[str]:
    if not statuses_text:
        return {"distilled", "skipped"}
    return {item.strip() for item in statuses_text.split(",") if item.strip()}


def cmd_prune(statuses_text: Optional[str], source_missing: bool, apply: bool) -> int:
    """Prune source-missing manifest placeholders."""
    ensure_dirs()
    statuses = parse_statuses(statuses_text)
    invalid_statuses = statuses.difference(HANDLED_MANIFEST_STATUSES)
    if invalid_statuses:
        print("==> Prune manifest placeholders")
        print(
            "  ! Prune refused: only handled statuses may be cleaned "
            f"({', '.join(sorted(HANDLED_MANIFEST_STATUSES))})"
        )
        print(f"    Invalid: {', '.join(sorted(invalid_statuses))}")
        return 1
    if not source_missing:
        print("==> Prune manifest placeholders")
        print("  ! Prune refused: cleanup is limited to source-missing handled placeholders")
        print("    Re-run with --source-missing.")
        return 1
    manifest = load_manifest()
    candidates = []
    kept = []
    for session in manifest["sessions"]:
        matches_status = session.get("status") in statuses
        matches_source = bool(session.get("source_missing"))
        if matches_status and matches_source:
            candidates.append(session)
        else:
            kept.append(session)

    print("==> Prune manifest placeholders")
    print(f"Statuses: {', '.join(sorted(statuses))}")
    print(f"Source missing required: {source_missing}")
    print(f"Candidates: {len(candidates)}")
    for session in candidates:
        print(f"  - {session['session_id']} ({session.get('status')})")

    if not apply:
        print("Dry-run only. Re-run with --apply to remove these manifest entries.")
        return 0

    manifest["sessions"] = kept
    save_manifest(manifest)
    print(f"Removed: {len(candidates)}")
    return 0


def extract_source_session_id(text: str) -> Optional[str]:
    patterns = [
        r"\[source:\s*`?([A-Za-z0-9_.-]{6,})`?\]",
        r"\(source:\s*`?([A-Za-z0-9_.-]{6,})`?\)",
        r"source(?: session)?\s*[:=]\s*`?([A-Za-z0-9_.-]{6,})`?",
        r"session(?: id)?\s*[:=]\s*`?([A-Za-z0-9_.-]{6,})`?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).rstrip(".,;)")
    return None


def note_has_no_promotion(session_id: str) -> bool:
    path = note_path_for(session_id)
    if not path.exists():
        return False
    promotion = section_text(path.read_text(encoding="utf-8", errors="replace"), "Promotion Decision")
    return bool(re.search(r"\bno promotion\b\s*:", promotion, re.IGNORECASE))


def classify_knowledge_entry(text: str, source_session_id: Optional[str]) -> tuple[str, list[str]]:
    lower = text.lower()
    reasons: list[str] = []

    if "superseded" in lower or "replaced by" in lower or "替代" in text:
        return "superseded", ["entry explicitly says it is superseded/replaced"]

    stale_terms = ("stale", "obsolete", "deprecated", "outdated", "no longer", "过期", "废弃")
    if any(term in lower for term in stale_terms):
        return "stale", ["entry uses stale/obsolete language"]

    if source_session_id and note_has_no_promotion(source_session_id):
        return "stale", ["source session note says No Promotion"]

    review_terms = (
        "todo",
        "pending",
        "tbd",
        "maybe",
        "workaround",
        "temporary",
        "one-off",
        "needs review",
        "待确认",
        "临时",
        "一次性",
    )
    if not source_session_id:
        reasons.append("missing source session id")
    if any(term in lower for term in review_terms):
        reasons.append("entry looks temporary or unresolved")
    if len(text) < 20:
        reasons.append("entry is too short to audit")

    if reasons:
        return "needs-review", reasons
    return "stable", ["source-linked reusable entry"]


def parse_knowledge_entries() -> list[KnowledgeEntry]:
    if not KNOWLEDGE_FILE.exists():
        return []

    entries: list[KnowledgeEntry] = []
    section = "root"
    for line_no, line in enumerate(KNOWLEDGE_FILE.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            section = stripped.lstrip("#").strip() or "root"
            continue
        if not (stripped.startswith("- ") or re.match(r"^\d+\.\s+", stripped)):
            continue

        text = re.sub(r"^(?:-|\d+\.)\s+", "", stripped)
        source_session_id = extract_source_session_id(text)
        status, reasons = classify_knowledge_entry(text, source_session_id)
        entries.append(
            KnowledgeEntry(
                section=section,
                line_no=line_no,
                text=text,
                source_session_id=source_session_id,
                status=status,
                reasons=reasons,
            )
        )
    return entries


def load_kb_review_state() -> Optional[dict[str, Any]]:
    if not KB_REVIEW_STATE_FILE.exists():
        return None
    try:
        payload = json.loads(KB_REVIEW_STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def maybe_print_kb_review_reminder() -> None:
    entries = parse_knowledge_entries()
    current_count = len(entries)
    if current_count == 0:
        return

    state = load_kb_review_state()
    if not state:
        if current_count < KB_REVIEW_REMINDER_THRESHOLD:
            return
        print("")
        print("==> Reminder: knowledge-base has not been reviewed yet")
        print(f"  Entries now: {current_count}")
        print("  Suggested: /hm:review-kb --next 20")
        return

    previous_count = int(state.get("total_entries") or 0)
    delta = current_count - previous_count
    if delta < KB_REVIEW_REMINDER_THRESHOLD:
        return

    reviewed_at = state.get("reviewed_at", "unknown")
    print("")
    print("==> Reminder: knowledge-base review is due")
    print(f"  Last review: {reviewed_at} at {previous_count} entries")
    print(f"  Entries now: {current_count} (+{delta})")
    print("  Suggested: /hm:review-kb --next 20")


def extract_keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,}", text.lower())
    seen: set[str] = set()
    keywords: list[str] = []
    for token in tokens:
        normalized = token.strip("_-")
        if not normalized or normalized in KEYWORD_STOPWORDS:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(normalized)
    return keywords


def related_knowledge_entries(
    text: str,
    source_session_id: str,
    limit: int = VERIFY_REMINDER_LIMIT,
) -> list[tuple[KnowledgeEntry, list[str]]]:
    keywords = extract_keywords(text)
    if not keywords:
        return []

    matches: list[tuple[KnowledgeEntry, list[str]]] = []
    for entry in parse_knowledge_entries():
        if entry.source_session_id == source_session_id:
            continue
        lower = entry.text.lower()
        hits = [keyword for keyword in keywords if keyword in lower]
        if len(hits) >= 2:
            matches.append((entry, hits[:5]))

    matches.sort(key=lambda item: (-len(item[1]), item[0].line_no))
    return matches[:limit]


def maybe_print_verify_entry_reminder(
    source_session_id: str,
    text: str,
    trigger: str,
) -> None:
    matches = related_knowledge_entries(text, source_session_id)
    if not matches:
        return

    print("")
    print(f"==> Reminder: {trigger} overlaps existing knowledge")
    for entry, hits in matches:
        source = entry.source_session_id or "none"
        query = hits[0]
        print(
            f"  - line {entry.line_no} [{entry.status}] "
            f"source={source} hits={', '.join(hits)}"
        )
        print(f"    Suggested: /hm:verify-entry {query}")


def cmd_review_kb(next_count: int) -> int:
    """Review knowledge-base entries with lightweight audit heuristics."""
    ensure_dirs()
    entries = parse_knowledge_entries()
    summary = {status: 0 for status in KNOWLEDGE_REVIEW_STATUSES}
    for entry in entries:
        summary[entry.status] = summary.get(entry.status, 0) + 1

    print("==> Knowledge Base Review")
    print(f"Entries: {len(entries)}")
    print(
        "Summary: "
        f"stable={summary.get('stable', 0)} | "
        f"needs-review={summary.get('needs-review', 0)} | "
        f"stale={summary.get('stale', 0)} | "
        f"superseded={summary.get('superseded', 0)}"
    )
    print("")

    for entry in entries[:next_count]:
        source = entry.source_session_id or "none"
        print(f"- line {entry.line_no} [{entry.status}] source={source} section={entry.section}")
        print(f"  {entry.text}")
        if entry.reasons:
            print(f"  reason: {'; '.join(entry.reasons)}")

    KB_REVIEW_STATE_FILE.write_text(
        json.dumps(
            {
                "reviewed_at": utc_now(),
                "total_entries": len(entries),
                "summary": summary,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


def backup_knowledge_base() -> Path:
    KB_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = KB_BACKUPS_DIR / f"knowledge-base-{timestamp}.md"
    shutil.copy2(KNOWLEDGE_FILE, backup_path)
    return backup_path


def cmd_prune_kb(statuses_text: Optional[str], dry_run: bool = False) -> int:
    """Prune knowledge-base entries by review status, with backup."""
    ensure_dirs()
    statuses = parse_statuses(statuses_text or "stale,superseded")
    invalid_statuses = statuses.difference(PRUNABLE_KB_STATUSES)
    if invalid_statuses:
        print("==> Knowledge Base Prune")
        print(
            "  ! Prune refused: knowledge-base cleanup is confined to "
            f"{', '.join(sorted(PRUNABLE_KB_STATUSES))}"
        )
        print(f"    Invalid: {', '.join(sorted(invalid_statuses))}")
        return 1
    entries = parse_knowledge_entries()
    remove_lines = {entry.line_no for entry in entries if entry.status in statuses}

    print("==> Knowledge Base Prune")
    print(f"Statuses: {', '.join(sorted(statuses))}")
    print(f"Candidates: {len(remove_lines)}")
    for entry in entries:
        if entry.line_no in remove_lines:
            print(f"  - line {entry.line_no} [{entry.status}] {entry.text}")

    if not remove_lines:
        print("Nothing to prune.")
        return 0

    if dry_run:
        print("Dry-run only. Re-run without --dry-run to prune with backup.")
        return 0

    backup_path = backup_knowledge_base()
    lines = KNOWLEDGE_FILE.read_text(encoding="utf-8").splitlines()
    kept = [line for line_no, line in enumerate(lines, 1) if line_no not in remove_lines]
    KNOWLEDGE_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"Backup: {backup_path}")
    print(f"Removed: {len(remove_lines)}")
    return 0


def cmd_verify_entry(query: str) -> int:
    """Show matching knowledge entries with grill-style recheck prompts."""
    ensure_dirs()
    entries = parse_knowledge_entries()
    lowered = query.lower()
    matches = [
        entry
        for entry in entries
        if lowered in entry.text.lower()
        or (entry.source_session_id and lowered in entry.source_session_id.lower())
    ]

    print(f"==> Verify Entry: {query}")
    if not matches:
        print("No matching knowledge entries.")
        return 1

    for entry in matches:
        source = entry.source_session_id or "none"
        print(f"- line {entry.line_no} [{entry.status}] source={source} section={entry.section}")
        print(f"  {entry.text}")
        print("  Recheck questions:")
        print("  1. Is this still true against current code/config/docs?")
        print("  2. Did a later session supersede or narrow this claim?")
        print("  3. Is this reusable workflow knowledge, or only a one-off note?")
        print("  4. Should it stay in knowledge-base, become needs-review, or move back to session note?")
    return 0


def cmd_prd_sync(dry_run: bool = True) -> int:
    """Generate PRD sync candidates from bundled packets."""
    print("==> PRD Sync: Generating candidates from bundled packets")
    print(f"    Dry-run: {dry_run}")
    print("")

    ensure_dirs()
    manifest = load_manifest()
    bundled = [s for s in manifest["sessions"] if s["status"] == "bundled"]

    if not bundled:
        print("  No bundled packets found. Run /hm:distill first.")
        return 0

    prd_keywords = [
        "prd",
        "roadmap",
        "launch",
        "v1",
        "feature",
        "architecture",
        "decision",
        "milestone",
        "scope",
        "requirement",
        "product",
    ]

    candidates = []
    for session in bundled:
        if not session.get("bundle_path"):
            continue
        bundle_path = Path(session["bundle_path"])
        if not bundle_path.exists():
            continue

        content = bundle_path.read_text(encoding="utf-8").lower()
        if any(kw in content for kw in prd_keywords):
            candidates.append(session)

    if not candidates:
        print("  No PRD-related packets found.")
        return 0

    print(f"  Found {len(candidates)} PRD-related packet(s):")
    for session in candidates:
        print(f"    - {session['session_id']}")

    today = datetime.now().strftime("%Y-%m-%d")
    distilled_path = PRD_DISTILLED_DIR / f"{today}-prd-sync-candidate.md"

    lines = [
        f"# PRD Sync Candidate - {today}",
        "",
        "> Candidate only. Review before editing canonical PRD or roadmap docs.",
        "",
        "## Source Packets",
        "",
    ]
    for session in candidates:
        lines.append(f"- `{session['session_id']}`")

    lines.extend(["", "## Detected Topics", "", "*(Auto-detected from packet content)*", ""])
    detected = set()
    for session in candidates:
        if session.get("bundle_path"):
            content = Path(session["bundle_path"]).read_text(encoding="utf-8")
            for kw in prd_keywords:
                if kw in content.lower():
                    detected.add(kw)
    for kw in sorted(detected):
        lines.append(f"- {kw}")

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This note is generated from bundled session-distill packets.",
            "- It does not update canonical PRD docs, roadmap docs, knowledge-base truth, or confirmed truth by itself.",
            "- Treat it as a review artifact before any manual product-doc edits.",
            "",
            "## Suggested Decision Records",
            "",
            "*(Placeholder - fill in after review)*",
            "",
            "```markdown",
            "## YYYY-MM-DD - <topic>",
            "- **status**: pending",
            "- **decision**: <summary>",
            "- **source**: <doc>",
            "- **rationale**: <distilled-path>",
            "```",
            "",
        ]
    )

    if not dry_run:
        PRD_DISTILLED_DIR.mkdir(parents=True, exist_ok=True)
        distilled_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  -> Generated candidate: {distilled_path}")
        print("  -> No canonical PRD/roadmap docs were modified.")
    else:
        print("  [DRY-RUN] No files written. Use --apply to confirm.")
        print("  [DRY-RUN] Candidate preview only; canonical PRD/roadmap docs remain unchanged.")
    return 0


def cmd_run(
    project_path: Optional[Path],
    force: bool = False,
    next_count: int = DEFAULT_RUN_NEXT,
) -> int:
    """Run preparation phase."""
    print("==> Session Distiller: Preparation Phase")
    print("")
    print("This command runs: index + bundle")
    print("AI/Slash commands handle distillation after")
    print("")

    ensure_dirs()
    cmd_index(project_path)
    cmd_bundle(project_path, force, next_count=next_count)

    print("")
    print("==> Preparation done")
    print("")
    print("Next steps:")
    print("  1. AI reads packets/")
    print("  2. AI writes session notes -> distilled/sessions/")
    print("  3. AI updates knowledge-base.md only for stable reusable lessons")
    print("  4. AI decides on project rules promotion")
    print("  5. User/agent invokes /hm:mark SESSION-ID distilled")
    print("")

    return cmd_status(project_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Session Distiller maintenance CLI")
    parser.add_argument("--project", help="Project name")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run")
    run.add_argument("--next", type=int, default=DEFAULT_RUN_NEXT)
    run.add_argument("--force", action="store_true")

    status = subparsers.add_parser("status")
    status.set_defaults(command="status")

    list_cmd = subparsers.add_parser("list")
    list_cmd.add_argument("--size", type=int, default=DEFAULT_LIST_MIN_SIZE_KB)

    mark = subparsers.add_parser("mark")
    mark.add_argument("session_id")
    mark.add_argument("status")
    mark.add_argument("--keep-raw", action="store_true")

    prune = subparsers.add_parser("prune")
    prune.add_argument("--statuses", default="distilled,skipped")
    prune.add_argument("--source-missing", action="store_true")
    prune.add_argument("--apply", action="store_true")
    prune.add_argument("--dry-run", action="store_true")

    review_kb = subparsers.add_parser("review-kb")
    review_kb.add_argument("--next", type=int, default=20)

    prune_kb = subparsers.add_parser("prune-kb")
    prune_kb.add_argument("--statuses", default="stale,superseded")
    prune_kb.add_argument("--dry-run", action="store_true")

    verify = subparsers.add_parser("verify-entry")
    verify.add_argument("query")

    prd = subparsers.add_parser("prd-sync")
    prd.add_argument("--apply", action="store_true")

    subparsers.add_parser("help")
    return parser


def resolve_project_path(args: argparse.Namespace) -> Optional[Path]:
    if args.project:
        return find_project_path(args.project)
    return find_project_path()


def dispatch_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.command or args.command == "help":
        parser.print_help()
        return 0

    projectless = {"mark", "prune", "review-kb", "prune-kb", "verify-entry", "prd-sync"}
    project_path = None if args.command in projectless else resolve_project_path(args)

    if args.command not in projectless and not project_path:
        print("Error: Cannot find project directory")
        print("Use --project to specify, or run from project directory")
        return 1

    if args.command == "run":
        return cmd_run(project_path, force=args.force, next_count=args.next)
    if args.command == "status":
        return cmd_status(project_path)
    if args.command == "list":
        return cmd_list(project_path, args.size)
    if args.command == "mark":
        return cmd_mark(args.session_id, args.status, keep_raw=args.keep_raw)
    if args.command == "prune":
        return cmd_prune(args.statuses, source_missing=args.source_missing, apply=args.apply)
    if args.command == "review-kb":
        return cmd_review_kb(args.next)
    if args.command == "prune-kb":
        return cmd_prune_kb(args.statuses, dry_run=args.dry_run)
    if args.command == "verify-entry":
        return cmd_verify_entry(args.query)
    if args.command == "prd-sync":
        return cmd_prd_sync(dry_run=not args.apply)

    parser.print_help()
    return 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return dispatch_command(args, parser)


if __name__ == "__main__":
    sys.exit(main())
