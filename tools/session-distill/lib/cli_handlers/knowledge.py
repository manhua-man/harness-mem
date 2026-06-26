"""Knowledge-base command handlers for session-distill."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Optional, TypeVar

from lib.models import KnowledgeEntry

EnsureDirs = Callable[[], None]
UtcNow = Callable[[], str]
ParseStatuses = Callable[[Optional[str]], set[str]]
NotePathFor = Callable[[str], Path]
SectionText = Callable[[str, str], str]
T = TypeVar("T")

KNOWLEDGE_FILE: Path | None = None
KB_REVIEW_STATE_FILE: Path | None = None
KB_BACKUPS_DIR: Path | None = None
KEYWORD_STOPWORDS: set[str] = set()
KNOWLEDGE_REVIEW_STATUSES: tuple[str, ...] = ()
PRUNABLE_KB_STATUSES: frozenset[str] = frozenset()
KB_REVIEW_REMINDER_THRESHOLD = 5
VERIFY_REMINDER_LIMIT = 5

_ensure_dirs: EnsureDirs | None = None
_utc_now: UtcNow | None = None
_parse_statuses: ParseStatuses | None = None
_note_path_for: NotePathFor | None = None
_section_text: SectionText | None = None


def configure(
    *,
    knowledge_file: Path,
    kb_review_state_file: Path,
    kb_backups_dir: Path,
    keyword_stopwords: set[str],
    knowledge_review_statuses: tuple[str, ...],
    prunable_kb_statuses: frozenset[str],
    kb_review_reminder_threshold: int,
    verify_reminder_limit: int,
    ensure_dirs: EnsureDirs,
    utc_now: UtcNow,
    parse_statuses: ParseStatuses,
    note_path_for: NotePathFor,
    section_text: SectionText,
) -> None:
    """Bind CLI-owned paths and helpers before executing a command."""
    global KNOWLEDGE_FILE, KB_REVIEW_STATE_FILE, KB_BACKUPS_DIR
    global KEYWORD_STOPWORDS, KNOWLEDGE_REVIEW_STATUSES, PRUNABLE_KB_STATUSES
    global KB_REVIEW_REMINDER_THRESHOLD, VERIFY_REMINDER_LIMIT
    global _ensure_dirs, _utc_now, _parse_statuses, _note_path_for, _section_text
    KNOWLEDGE_FILE = knowledge_file
    KB_REVIEW_STATE_FILE = kb_review_state_file
    KB_BACKUPS_DIR = kb_backups_dir
    KEYWORD_STOPWORDS = keyword_stopwords
    KNOWLEDGE_REVIEW_STATUSES = knowledge_review_statuses
    PRUNABLE_KB_STATUSES = prunable_kb_statuses
    KB_REVIEW_REMINDER_THRESHOLD = kb_review_reminder_threshold
    VERIFY_REMINDER_LIMIT = verify_reminder_limit
    _ensure_dirs = ensure_dirs
    _utc_now = utc_now
    _parse_statuses = parse_statuses
    _note_path_for = note_path_for
    _section_text = section_text


def _configured_path(value: Path | None, name: str) -> Path:
    if value is None:
        raise RuntimeError(f"knowledge handler is not configured: {name}")
    return value


def _configured_callable(value: T | None, name: str) -> T:
    if value is None:
        raise RuntimeError(f"knowledge handler is not configured: {name}")
    return value


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
    note_path_for = _configured_callable(_note_path_for, "note_path_for")
    section_text = _configured_callable(_section_text, "section_text")
    path = note_path_for(session_id)
    if not path.exists():
        return False
    promotion = section_text(
        path.read_text(encoding="utf-8", errors="replace"),
        "Promotion Decision",
    )
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
    knowledge_file = _configured_path(KNOWLEDGE_FILE, "knowledge_file")
    if not knowledge_file.exists():
        return []

    entries: list[KnowledgeEntry] = []
    section = "root"
    for line_no, line in enumerate(knowledge_file.read_text(encoding="utf-8").splitlines(), 1):
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


def load_kb_review_state() -> Optional[dict[str, object]]:
    state_file = _configured_path(KB_REVIEW_STATE_FILE, "kb_review_state_file")
    if not state_file.exists():
        return None
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
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
    limit: int | None = None,
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
    return matches[: limit or VERIFY_REMINDER_LIMIT]


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
    ensure_dirs = _configured_callable(_ensure_dirs, "ensure_dirs")
    utc_now = _configured_callable(_utc_now, "utc_now")
    state_file = _configured_path(KB_REVIEW_STATE_FILE, "kb_review_state_file")

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

    state_file.write_text(
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
    knowledge_file = _configured_path(KNOWLEDGE_FILE, "knowledge_file")
    backups_dir = _configured_path(KB_BACKUPS_DIR, "kb_backups_dir")
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"knowledge-base-{timestamp}.md"
    shutil.copy2(knowledge_file, backup_path)
    return backup_path


def cmd_prune_kb(statuses_text: Optional[str], dry_run: bool = False) -> int:
    """Prune knowledge-base entries by review status, with backup."""
    ensure_dirs = _configured_callable(_ensure_dirs, "ensure_dirs")
    parse_statuses = _configured_callable(_parse_statuses, "parse_statuses")
    knowledge_file = _configured_path(KNOWLEDGE_FILE, "knowledge_file")

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
    lines = knowledge_file.read_text(encoding="utf-8").splitlines()
    kept = [line for line_no, line in enumerate(lines, 1) if line_no not in remove_lines]
    knowledge_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"Backup: {backup_path}")
    print(f"Removed: {len(remove_lines)}")
    return 0


def cmd_verify_entry(query: str) -> int:
    """Show matching knowledge entries with grill-style recheck prompts."""
    ensure_dirs = _configured_callable(_ensure_dirs, "ensure_dirs")

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
