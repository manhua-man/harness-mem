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
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

# Allow importing vendored parser from lib/parser.py.
_SKILL_ROOT = Path(__file__).resolve().parent.parent
_LIB_DIR = _SKILL_ROOT / "lib"
if _LIB_DIR.exists():
    sys.path.insert(0, str(_SKILL_ROOT))

from lib.models import KnowledgeEntry  # noqa: E402
from lib.cli_handlers.knowledge import (  # noqa: E402
    backup_knowledge_base as _backup_knowledge_base,
    classify_knowledge_entry as _classify_knowledge_entry,
    cmd_prune_kb as _cmd_prune_kb,
    cmd_review_kb as _cmd_review_kb,
    cmd_verify_entry as _cmd_verify_entry,
    configure as _configure_knowledge_handlers,
    extract_keywords as _extract_keywords,
    extract_source_session_id as _extract_source_session_id,
    load_kb_review_state as _load_kb_review_state,
    maybe_print_kb_review_reminder as _maybe_print_kb_review_reminder,
    maybe_print_verify_entry_reminder as _maybe_print_verify_entry_reminder,
    note_has_no_promotion as _note_has_no_promotion,
    parse_knowledge_entries as _parse_knowledge_entries,
    related_knowledge_entries as _related_knowledge_entries,
)
from lib.cli_handlers.lifecycle import (  # noqa: E402
    append_pruned_source as _append_pruned_source,
    bundle_path_for as _bundle_path_for,
    cmd_mark as _cmd_mark,
    cmd_prune as _cmd_prune,
    configure as _configure_lifecycle_handlers,
    draft_has_pending as _draft_has_pending,
    find_manifest_session as _find_manifest_session,
    maybe_delete_raw_source as _maybe_delete_raw_source,
    note_path_for as _note_path_for,
    packet_is_partial as _packet_is_partial,
    parse_statuses as _parse_statuses,
    section_text as _section_text,
    validate_distilled_guardrails as _validate_distilled_guardrails,
    validate_same_source_kb as _validate_same_source_kb,
    validate_session_note as _validate_session_note,
)
from lib.cli_handlers.prd import cmd_prd_sync as _cmd_prd_sync  # noqa: E402
from lib.cli_handlers.project import (  # noqa: E402
    cmd_bundle as _cmd_bundle,
    cmd_index as _cmd_index,
    cmd_list as _cmd_list,
    cmd_run as _cmd_run,
    cmd_status as _cmd_status,
    configure as _configure_project_handlers,
    generate_packet as _generate_packet,
    pending_sessions as _pending_sessions,
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


def _sync_project_handlers() -> None:
    _configure_project_handlers(
        manifest_file=MANIFEST_FILE,
        knowledge_file=KNOWLEDGE_FILE,
        packets_dir=PACKETS_DIR,
        default_run_next=DEFAULT_RUN_NEXT,
        ensure_dirs=ensure_dirs,
        load_manifest=load_manifest,
        save_manifest=save_manifest,
        source_signature=source_signature,
        maybe_print_verify_entry_reminder=maybe_print_verify_entry_reminder,
    )


def cmd_index(project_path: Optional[Path]) -> int:
    _sync_project_handlers()
    return _cmd_index(project_path)


def pending_sessions(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    _sync_project_handlers()
    return _pending_sessions(manifest)


def cmd_bundle(
    project_path: Optional[Path],
    force: bool = False,
    next_count: int = DEFAULT_RUN_NEXT,
) -> int:
    _sync_project_handlers()
    return _cmd_bundle(project_path, force=force, next_count=next_count)


def generate_packet(session: dict[str, Any], packet_path: Path) -> None:
    _sync_project_handlers()
    _generate_packet(session, packet_path)


def cmd_status(project_path: Optional[Path]) -> int:
    _sync_project_handlers()
    return _cmd_status(project_path)


def cmd_list(project_path: Optional[Path], min_size: int = 100) -> int:
    _sync_project_handlers()
    return _cmd_list(project_path, min_size=min_size)

def _sync_lifecycle_handlers() -> None:
    _configure_lifecycle_handlers(
        distilled_dir=DISTILLED_DIR,
        packets_dir=PACKETS_DIR,
        memory_drafts_dir=MEMORY_DRAFTS_DIR,
        pruned_sources_file=PRUNED_SOURCES_FILE,
        codex_raw_roots=CODEX_RAW_ROOTS,
        required_note_sections=REQUIRED_NOTE_SECTIONS,
        handled_manifest_statuses=HANDLED_MANIFEST_STATUSES,
        ensure_dirs=ensure_dirs,
        load_manifest=load_manifest,
        save_manifest=save_manifest,
        utc_now=utc_now,
        parse_knowledge_entries=parse_knowledge_entries,
        maybe_print_verify_entry_reminder=maybe_print_verify_entry_reminder,
        maybe_print_kb_review_reminder=maybe_print_kb_review_reminder,
    )


def find_manifest_session(manifest: dict[str, Any], session_id: str) -> Optional[dict[str, Any]]:
    _sync_lifecycle_handlers()
    return _find_manifest_session(manifest, session_id)


def note_path_for(session_id: str, session: Optional[dict[str, Any]] = None) -> Path:
    _sync_lifecycle_handlers()
    return _note_path_for(session_id, session)


def bundle_path_for(session_id: str, session: Optional[dict[str, Any]] = None) -> Path:
    _sync_lifecycle_handlers()
    return _bundle_path_for(session_id, session)


def section_text(markdown: str, heading: str) -> str:
    _sync_lifecycle_handlers()
    return _section_text(markdown, heading)


def packet_is_partial(session_id: str, session: Optional[dict[str, Any]] = None) -> bool:
    _sync_lifecycle_handlers()
    return _packet_is_partial(session_id, session)


def validate_session_note(session_id: str, session: dict[str, Any]) -> list[str]:
    _sync_lifecycle_handlers()
    return _validate_session_note(session_id, session)


def draft_has_pending(session_id: str) -> tuple[bool, Optional[Path]]:
    _sync_lifecycle_handlers()
    return _draft_has_pending(session_id)


def append_pruned_source(record: dict[str, Any]) -> None:
    _sync_lifecycle_handlers()
    _append_pruned_source(record)


def maybe_delete_raw_source(session: dict[str, Any], keep_raw: bool) -> None:
    _sync_lifecycle_handlers()
    _maybe_delete_raw_source(session, keep_raw)


def validate_same_source_kb(session_id: str) -> list[str]:
    _sync_lifecycle_handlers()
    return _validate_same_source_kb(session_id)


def validate_distilled_guardrails(session_id: str, session: dict[str, Any]) -> list[str]:
    _sync_lifecycle_handlers()
    return _validate_distilled_guardrails(session_id, session)


def cmd_mark(session_id: str, status: str, keep_raw: bool = False) -> int:
    _sync_lifecycle_handlers()
    return _cmd_mark(session_id, status, keep_raw=keep_raw)


def parse_statuses(statuses_text: Optional[str]) -> set[str]:
    return _parse_statuses(statuses_text)


def cmd_prune(statuses_text: Optional[str], source_missing: bool, apply: bool) -> int:
    _sync_lifecycle_handlers()
    return _cmd_prune(statuses_text, source_missing=source_missing, apply=apply)

def _sync_knowledge_handlers() -> None:
    _configure_knowledge_handlers(
        knowledge_file=KNOWLEDGE_FILE,
        kb_review_state_file=KB_REVIEW_STATE_FILE,
        kb_backups_dir=KB_BACKUPS_DIR,
        keyword_stopwords=KEYWORD_STOPWORDS,
        knowledge_review_statuses=KNOWLEDGE_REVIEW_STATUSES,
        prunable_kb_statuses=PRUNABLE_KB_STATUSES,
        kb_review_reminder_threshold=KB_REVIEW_REMINDER_THRESHOLD,
        verify_reminder_limit=VERIFY_REMINDER_LIMIT,
        ensure_dirs=ensure_dirs,
        utc_now=utc_now,
        parse_statuses=parse_statuses,
        note_path_for=note_path_for,
        section_text=section_text,
    )


def extract_source_session_id(text: str) -> Optional[str]:
    return _extract_source_session_id(text)


def note_has_no_promotion(session_id: str) -> bool:
    _sync_knowledge_handlers()
    return _note_has_no_promotion(session_id)


def classify_knowledge_entry(text: str, source_session_id: Optional[str]) -> tuple[str, list[str]]:
    _sync_knowledge_handlers()
    return _classify_knowledge_entry(text, source_session_id)


def parse_knowledge_entries() -> list[KnowledgeEntry]:
    _sync_knowledge_handlers()
    return _parse_knowledge_entries()


def load_kb_review_state() -> Optional[dict[str, Any]]:
    _sync_knowledge_handlers()
    state = _load_kb_review_state()
    return state if state is None else dict(state)


def maybe_print_kb_review_reminder() -> None:
    _sync_knowledge_handlers()
    _maybe_print_kb_review_reminder()


def extract_keywords(text: str) -> list[str]:
    _sync_knowledge_handlers()
    return _extract_keywords(text)


def related_knowledge_entries(
    text: str,
    source_session_id: str,
    limit: int = VERIFY_REMINDER_LIMIT,
) -> list[tuple[KnowledgeEntry, list[str]]]:
    _sync_knowledge_handlers()
    return _related_knowledge_entries(text, source_session_id, limit=limit)


def maybe_print_verify_entry_reminder(
    source_session_id: str,
    text: str,
    trigger: str,
) -> None:
    _sync_knowledge_handlers()
    _maybe_print_verify_entry_reminder(source_session_id, text, trigger)


def cmd_review_kb(next_count: int) -> int:
    _sync_knowledge_handlers()
    return _cmd_review_kb(next_count)


def backup_knowledge_base() -> Path:
    _sync_knowledge_handlers()
    return _backup_knowledge_base()


def cmd_prune_kb(statuses_text: Optional[str], dry_run: bool = False) -> int:
    _sync_knowledge_handlers()
    return _cmd_prune_kb(statuses_text, dry_run=dry_run)


def cmd_verify_entry(query: str) -> int:
    _sync_knowledge_handlers()
    return _cmd_verify_entry(query)


def cmd_prd_sync(dry_run: bool = True) -> int:
    return _cmd_prd_sync(
        dry_run=dry_run,
        ensure_dirs=ensure_dirs,
        load_manifest=load_manifest,
        prd_distilled_dir=PRD_DISTILLED_DIR,
    )


def cmd_run(
    project_path: Optional[Path],
    force: bool = False,
    next_count: int = DEFAULT_RUN_NEXT,
) -> int:
    _sync_project_handlers()
    return _cmd_run(project_path, force=force, next_count=next_count)


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
