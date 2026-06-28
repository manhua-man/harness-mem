"""Session lifecycle command handlers for session-distill."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from lib.guardrails import contains_pending_draft, raw_deletion_root

EnsureDirs = Callable[[], None]
LoadManifest = Callable[[], dict[str, Any]]
SaveManifest = Callable[[dict[str, Any]], None]
UtcNow = Callable[[], str]
T = TypeVar("T")

DISTILLED_DIR: Path | None = None
PACKETS_DIR: Path | None = None
MEMORY_DRAFTS_DIR: Path | None = None
PRUNED_SOURCES_FILE: Path | None = None
CODEX_RAW_ROOTS: tuple[Path, ...] = ()
REQUIRED_NOTE_SECTIONS: tuple[str, ...] = ()
HANDLED_MANIFEST_STATUSES: frozenset[str] = frozenset()

_ensure_dirs: EnsureDirs | None = None
_load_manifest: LoadManifest | None = None
_save_manifest: SaveManifest | None = None
_utc_now: UtcNow | None = None


def configure(
    *,
    distilled_dir: Path,
    packets_dir: Path,
    memory_drafts_dir: Path,
    pruned_sources_file: Path,
    codex_raw_roots: tuple[Path, ...],
    required_note_sections: tuple[str, ...],
    handled_manifest_statuses: frozenset[str],
    ensure_dirs: EnsureDirs,
    load_manifest: LoadManifest,
    save_manifest: SaveManifest,
    utc_now: UtcNow,
) -> None:
    """Bind CLI-owned paths and helpers before executing a lifecycle command."""
    global DISTILLED_DIR, PACKETS_DIR, MEMORY_DRAFTS_DIR, PRUNED_SOURCES_FILE
    global CODEX_RAW_ROOTS, REQUIRED_NOTE_SECTIONS, HANDLED_MANIFEST_STATUSES
    global _ensure_dirs, _load_manifest, _save_manifest, _utc_now
    DISTILLED_DIR = distilled_dir
    PACKETS_DIR = packets_dir
    MEMORY_DRAFTS_DIR = memory_drafts_dir
    PRUNED_SOURCES_FILE = pruned_sources_file
    CODEX_RAW_ROOTS = codex_raw_roots
    REQUIRED_NOTE_SECTIONS = required_note_sections
    HANDLED_MANIFEST_STATUSES = handled_manifest_statuses
    _ensure_dirs = ensure_dirs
    _load_manifest = load_manifest
    _save_manifest = save_manifest
    _utc_now = utc_now


def _configured_path(value: Path | None, name: str) -> Path:
    if value is None:
        raise RuntimeError(f"lifecycle handler is not configured: {name}")
    return value


def _configured_callable(value: T | None, name: str) -> T:
    if value is None:
        raise RuntimeError(f"lifecycle handler is not configured: {name}")
    return value


def find_manifest_session(manifest: dict[str, Any], session_id: str) -> Optional[dict[str, Any]]:
    for session in manifest["sessions"]:
        if session["session_id"] == session_id:
            return session
    return None


def note_path_for(session_id: str, session: Optional[dict[str, Any]] = None) -> Path:
    if session and session.get("distilled_path"):
        return Path(session["distilled_path"])
    return _configured_path(DISTILLED_DIR, "distilled_dir") / f"{session_id}.md"


def bundle_path_for(session_id: str, session: Optional[dict[str, Any]] = None) -> Path:
    if session and session.get("bundle_path"):
        return Path(session["bundle_path"])
    return _configured_path(PACKETS_DIR, "packets_dir") / f"{session_id}.md"


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
    draft_path = _configured_path(MEMORY_DRAFTS_DIR, "memory_drafts_dir") / f"{session_id}.json"
    if not draft_path.exists():
        return False, None
    try:
        payload = json.loads(draft_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True, draft_path

    return contains_pending_draft(payload), draft_path


def append_pruned_source(record: dict[str, Any]) -> None:
    pruned_sources_file = _configured_path(PRUNED_SOURCES_FILE, "pruned_sources_file")
    pruned_sources_file.parent.mkdir(parents=True, exist_ok=True)
    with pruned_sources_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def maybe_delete_raw_source(session: dict[str, Any], keep_raw: bool) -> None:
    utc_now = _configured_callable(_utc_now, "utc_now")
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


def validate_distilled_guardrails(session_id: str, session: dict[str, Any]) -> list[str]:
    """Return closure guardrail failures for the internal distilled marker."""
    errors = []
    errors.extend(validate_session_note(session_id, session))
    pending, draft_path = draft_has_pending(session_id)
    if pending:
        errors.append(f"memory draft still has pending entries: {draft_path}")
    return errors


def cmd_mark(session_id: str, status: str, keep_raw: bool = False) -> int:
    """Mark session status after running guardrails for distilled sessions."""
    ensure_dirs = _configured_callable(_ensure_dirs, "ensure_dirs")
    load_manifest = _configured_callable(_load_manifest, "load_manifest")
    save_manifest = _configured_callable(_save_manifest, "save_manifest")
    utc_now = _configured_callable(_utc_now, "utc_now")

    if not session_id or not status:
        print("Usage: internal session closure requires SESSION-ID and STATUS")
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
    print("==> Mark done")
    return 0


def parse_statuses(statuses_text: Optional[str]) -> set[str]:
    if not statuses_text:
        return {"distilled", "skipped"}
    return {item.strip() for item in statuses_text.split(",") if item.strip()}


def cmd_prune(statuses_text: Optional[str], source_missing: bool, apply: bool) -> int:
    """Prune source-missing manifest placeholders."""
    ensure_dirs = _configured_callable(_ensure_dirs, "ensure_dirs")
    load_manifest = _configured_callable(_load_manifest, "load_manifest")
    save_manifest = _configured_callable(_save_manifest, "save_manifest")

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
