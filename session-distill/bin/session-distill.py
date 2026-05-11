#!/usr/bin/env python3
"""
Claude Code Session Distiller - Python implementation
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Allow importing vendored parser from lib/parser.py
# This works both in development (running from repo) and in production
# (skill installed at ~/.claude/skills/session-distill/).
_SKILL_ROOT = Path(__file__).resolve().parent.parent
_LIB_DIR = _SKILL_ROOT / "lib"
if _LIB_DIR.exists():
    sys.path.insert(0, str(_SKILL_ROOT))

from lib.parser import (  # noqa: E402  # isort:skip
    list_session_files,
    parse_claude_jsonl_session,
    select_turns_for_packet,
)

# Configuration
DISTILL_DIR = Path.home() / ".claude" / "session-distill"
MANIFEST_FILE = DISTILL_DIR / "manifest.json"
KNOWLEDGE_FILE = DISTILL_DIR / "knowledge-base.md"
PACKETS_DIR = DISTILL_DIR / "packets"
DISTILLED_DIR = DISTILL_DIR / "distilled" / "sessions"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
# PRD sync configuration
PRD_DISTILLED_DIR = Path.home() / ".claude" / "session-distill" / "prd-distilled"
PRD_DECISION_LOG = Path.home() / ".claude" / "session-distill" / "prd-decision-log-candidate.md"
DEFAULT_RUN_NEXT = 3
DEFAULT_LIST_MIN_SIZE_KB = 100


def ensure_dirs():
    """Create necessary directories"""
    DISTILL_DIR.mkdir(parents=True, exist_ok=True)
    PACKETS_DIR.mkdir(parents=True, exist_ok=True)
    DISTILLED_DIR.mkdir(parents=True, exist_ok=True)

    if not KNOWLEDGE_FILE.exists():
        KNOWLEDGE_FILE.write_text("# Session Distill Knowledge Base\n")

    if not MANIFEST_FILE.exists():
        manifest = {"version": 1, "updated_at": "", "sessions": []}
        save_manifest(manifest)


def load_manifest():
    """Load manifest file"""
    if MANIFEST_FILE.exists():
        return json.loads(MANIFEST_FILE.read_text())
    return {"version": 1, "updated_at": "", "sessions": []}


def save_manifest(manifest):
    """Save manifest file"""
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))


def find_project_path(project_name=None):
    """Find project directory"""
    if not project_name:
        project_name = Path.cwd().name

    project_path = PROJECTS_DIR / project_name
    if project_path.exists():
        return project_path
    return None


def source_signature(session):
    """Return a comparable signature for a session file."""
    path = Path(session["path"])
    stat = path.stat()
    return {
        "file_path": str(path),
        "file_size_bytes": stat.st_size,
        "source_mtime": stat.st_mtime,
        "size": f"{stat.st_size / 1024:.1f}KB",
        "last_seen_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def cmd_index(project_path):
    """Index sessions"""
    print("==> Index: Scanning sessions")
    manifest = load_manifest()
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
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
            manifest["sessions"].append({
                "session_id": session_id,
                "file_name": session["name"],
                **signature,
                "status": "new",
                "bundle_path": None,
                "distilled_path": None,
                "notes": ""
            })
            new_count += 1
            continue

        changed = (
            existing.get("file_path") != signature["file_path"]
            or existing.get("file_size_bytes") != signature["file_size_bytes"]
            or existing.get("source_mtime") != signature["source_mtime"]
        )

        existing["file_name"] = session["name"]
        existing["size"] = signature["size"]
        existing["file_path"] = signature["file_path"]
        existing["file_size_bytes"] = signature["file_size_bytes"]
        existing["source_mtime"] = signature["source_mtime"]
        existing["last_seen_at"] = signature["last_seen_at"]

        if changed:
            existing["status"] = "new"
            existing["bundle_path"] = None
            existing["distilled_path"] = None
            refreshed_count += 1
            print(f"  ~ Refreshed: {session['name']} ({session['size']})")

    manifest["updated_at"] = timestamp
    save_manifest(manifest)
    print(f"==> Index done: {new_count} new sessions, {refreshed_count} refreshed")


def pending_sessions(manifest):
    """Return bundle candidates sorted by freshest source first."""
    candidates = [s for s in manifest["sessions"] if s["status"] in ["new", "bundled"]]
    return sorted(
        candidates,
        key=lambda s: s.get("source_mtime", 0),
        reverse=True,
    )


def cmd_bundle(project_path, force=False, next_count=DEFAULT_RUN_NEXT):
    """Generate packets"""
    print("==> Bundle: Generating packets")
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
        session["status"] = "bundled"
        session["bundle_path"] = str(packet_path)
        count += 1

    save_manifest(manifest)
    print(f"==> Bundle done: {count} packets")


def generate_packet(session, packet_path):
    """Generate a packet file with actual session content"""
    session_path = Path(session['file_path'])
    all_turns = parse_claude_jsonl_session(session_path, filter_xml_directives=True, on_error="warn")
    turns, omitted_turns = select_turns_for_packet(all_turns)

    lines = [
        f"# Session Packet: {session['session_id']}",
        "",
        "## Metadata",
        "",
        f"- Source: `{session['file_name']}`",
        f"- Size: {session['size']}",
        f"- Path: `{session['file_path']}`",
        "",
        "## Distillation Reminder",
        "",
        "- Promote stable workflows, commands, file maps",
        "- Reject noise: token accounting, duplicate context",
        "- One-off context stays in session note",
        "",
    ]

    if not turns:
        lines.extend([
            "## Content",
            "",
            "(No parseable content found in this session)",
            ""
        ])
    else:
        if omitted_turns:
            lines.extend([
                "## Packet Scope",
                "",
                f"- Total parsed turns: {len(all_turns)}",
                f"- Included turns: {len(turns)}",
                f"- Omitted middle turns: {omitted_turns}",
                "- Strategy: keep the beginning request and the ending resolution",
                "",
            ])

        for i, turn in enumerate(turns, 1):
            lines.extend([
                f"## Turn {i}",
                "",
            ])

            if turn.get('user'):
                lines.extend([
                    "### User Request",
                    "",
                    "```text",
                    turn['user'],
                    "```",
                    ""
                ])

            if turn.get('assistant'):
                lines.extend([
                    "### Assistant Response",
                    ""
                ])
                for resp in turn['assistant'][:2]:  # Max 2 responses per turn
                    lines.extend([
                        "```text",
                        resp,
                        "```",
                        ""
                    ])

            if turn.get('tools'):
                lines.extend([
                    "### Tools Used",
                    ""
                ])
                for tool in turn['tools'][:5]:  # Max 5 tools per turn
                    lines.append(f"- `{tool['name']}`: {tool['input']}")
                lines.append("")

    lines.extend([
        "---",
        "",
        "## Suggested Next Step",
        "",
        "1. Read this packet",
        "2. Query existing memory for dedup",
        f"3. Write session note -> distilled/sessions/{session['session_id']}.md",
        "4. Append to knowledge-base.md",
        "5. Decide whether to promote to project rules",
        f"6. Run: session-distill mark {session['session_id']} distilled",
        ""
    ])

    packet_path.write_text('\n'.join(lines), encoding='utf-8')


def cmd_status(project_path):
    """Show status"""
    print("==> Session Distiller Status")
    print("")

    if not MANIFEST_FILE.exists():
        print("No sessions recorded yet")
        return

    manifest = load_manifest()
    total = len(manifest["sessions"])
    new = sum(1 for s in manifest["sessions"] if s["status"] == "new")
    bundled = sum(1 for s in manifest["sessions"] if s["status"] == "bundled")
    distilled = sum(1 for s in manifest["sessions"] if s["status"] == "distilled")
    skipped = sum(1 for s in manifest["sessions"] if s["status"] == "skipped")

    print(f"Sessions: {total} total | new={new} | bundled={bundled} | distilled={distilled} | skipped={skipped}")
    print("")

    if bundled > 0:
        print("Pending packets:")
        for session in manifest["sessions"]:
            if session["status"] == "bundled":
                print(f"  - {session['session_id']}")
        print("")

    kb_lines = len(KNOWLEDGE_FILE.read_text().splitlines()) if KNOWLEDGE_FILE.exists() else 0
    print(f"Knowledge base: {KNOWLEDGE_FILE} ({kb_lines} lines)")


def cmd_list(project_path, min_size=100):
    """List available sessions"""
    print("==> Available Sessions")
    print("")

    sessions = list_session_files(project_path, min_size_kb=min_size) if project_path else []
    if not sessions:
        print(f"No sessions found larger than {min_size}KB")
        return

    print(f"{'Size':<8} {'Lines':<6} {'Modified':<12} Filename")
    print("-" * 60)
    for session in sessions:
        mtime_str = session['mtime'].strftime("%Y-%m-%d") if hasattr(session['mtime'], 'strftime') else str(session['mtime'])
        print(f"{session['size']:<8} {session['lines']:<6} {mtime_str:<12} {session['name']}")


def cmd_mark(session_id, status):
    """Mark session status"""
    if not session_id or not status:
        print("Usage: session-distill mark SESSION-ID STATUS")
        return 1

    print("==> Mark: Updating status")
    manifest = load_manifest()

    found = False
    for session in manifest["sessions"]:
        if session["session_id"] == session_id:
            session["status"] = status
            found = True
            break

    if not found:
        print(f"  ! Session not found: {session_id}")
        return 1

    save_manifest(manifest)
    print(f"  -> {session_id} -> {status}")
    print("==> Mark done")
    return 0


def cmd_prd_sync(project_path, dry_run=True):
    """Generate PRD sync candidates from bundled packets"""
    print("==> PRD Sync: Generating candidates from bundled packets")
    print(f"    Dry-run: {dry_run}")
    print("")

    manifest = load_manifest()
    bundled = [s for s in manifest["sessions"] if s["status"] == "bundled"]

    if not bundled:
        print("  No bundled packets found. Run 'session-distill run' first.")
        return

    # Scan bundled packets for PRD-related content
    prd_keywords = [
        "prd", "roadmap", "launch", "v1", "feature", "architecture",
        "decision", "milestone", "scope", "requirement", "product"
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
        return

    print(f"  Found {len(candidates)} PRD-related packet(s):")
    for session in candidates:
        print(f"    - {session['session_id']}")

    print("")
    print("  Generating candidates...")

    # Generate distilled candidate
    today = datetime.now().strftime("%Y-%m-%d")
    distilled_path = PRD_DISTILLED_DIR / f"{today}-prd-sync-candidate.md"
    PRD_DISTILLED_DIR.mkdir(parents=True, exist_ok=True)

    # Extract PRD-relevant turns from packets
    lines = [
        f"# PRD Sync Candidate — {today}",
        "",
        "## Source Packets",
        "",
    ]

    for session in candidates:
        lines.append(f"- `{session['session_id']}`")

    lines.extend([
        "",
        "## Detected Topics",
        "",
        "*(Auto-detected from packet content)*",
        "",
    ])

    # Simple keyword extraction
    detected = set()
    for session in candidates:
        if session.get("bundle_path"):
            content = Path(session["bundle_path"]).read_text(encoding="utf-8")
            for kw in prd_keywords:
                if kw in content.lower():
                    detected.add(kw)
    for kw in sorted(detected):
        lines.append(f"- {kw}")

    lines.extend([
        "",
        "## Suggested Decision Records",
        "",
        "*(Placeholder — fill in after review)*",
        "",
        "```markdown",
        "## YYYY-MM-DD — <topic>",
        "- **status**: pending",
        "- **decision**: <summary>",
        "- **source**: <doc>",
        "- **rationale**: <distilled-path>",
        "```",
        "",
        "## Next Steps",
        "",
        "1. Review this candidate",
        "2. Fill in decision records",
        "3. Run: session-distill prd-sync --apply",
        "",
    ])

    distilled_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  -> Generated: {distilled_path}")

    # Generate decision log candidate
    decision_lines = [
        f"# Decision Log Candidate — {today}",
        "",
        "```markdown",
    ]

    for session in candidates:
        session_id = session["session_id"]
        decision_lines.extend([
            f"## {today} — {session_id}",
            "- **status**: pending",
            f"- **decision**: (from `{session_id}`)",
            f"- **source**: {session.get('bundle_path', 'unknown')}",
            "- **rationale**: <fill in>",
            "",
        ])

    decision_lines.extend([
        "```",
        "",
        "## To Apply",
        "",
        "Copy the above into `docs/prd/decision-log.md` after review.",
        "",
    ])

    decision_path = PRD_DECISION_LOG
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text("\n".join(decision_lines), encoding="utf-8")
    print(f"  -> Generated: {decision_path}")

    print("")
    if dry_run:
        print("  [DRY-RUN] No files written. Use --apply to confirm.")
    else:
        print("  [APPLIED] Candidates written.")


def cmd_run(project_path, force=False, next_count=DEFAULT_RUN_NEXT):
    """Run preparation phase"""
    print("==> Session Distiller: Preparation Phase")
    print("")
    print("This command runs: index + bundle")
    print("AI will handle distillation after")
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
    print("  3. AI appends to knowledge-base.md")
    print("  4. AI decides on project rules promotion")
    print("  5. Run: session-distill mark SESSION-ID distilled")
    print("")

    cmd_status(project_path)


def main():
    parser = argparse.ArgumentParser(description="Claude Code Session Distiller")
    parser.add_argument("command", nargs="?", choices=["run", "status", "list", "mark", "prd-sync", "help"], default="help")
    parser.add_argument("--project", help="Project name")
    parser.add_argument("--next", type=int, default=DEFAULT_RUN_NEXT, help="Number of pending sessions to bundle for run")
    parser.add_argument("--size", type=int, default=DEFAULT_LIST_MIN_SIZE_KB, help="Minimum session size in KB for list")
    parser.add_argument("--force", action="store_true", help="Force regeneration")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Dry-run mode (default)")
    parser.add_argument("--apply", action="store_true", help="Apply changes instead of dry-run")
    parser.add_argument("args", nargs="*", help="Additional arguments")

    args = parser.parse_args()

    if args.command == "help":
        parser.print_help()
        return 0

    if args.command == "mark":
        if len(args.args) < 2:
            print("Usage: session-distill mark SESSION-ID STATUS")
            return 1
        return cmd_mark(args.args[0], args.args[1])

    # Find project path
    project_path = None
    if args.project:
        project_path = find_project_path(args.project)
    else:
        project_path = find_project_path()

    if not project_path and args.command != "mark":
        print("Error: Cannot find project directory")
        print("Use --project to specify, or run from project directory")
        return 1

    if args.command == "run":
        cmd_run(project_path, args.force, args.next)
    elif args.command == "status":
        cmd_status(project_path)
    elif args.command == "list":
        cmd_list(project_path, args.size)
    elif args.command == "prd-sync":
        dry_run = not args.apply
        cmd_prd_sync(project_path, dry_run=dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
