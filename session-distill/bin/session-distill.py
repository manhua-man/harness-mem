#!/usr/bin/env python3
"""
Claude Code Session Distiller - Python implementation
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import UTC, datetime

# Configuration
DISTILL_DIR = Path.home() / ".claude" / "session-distill"
MANIFEST_FILE = DISTILL_DIR / "manifest.json"
KNOWLEDGE_FILE = DISTILL_DIR / "knowledge-base.md"
PACKETS_DIR = DISTILL_DIR / "packets"
DISTILLED_DIR = DISTILL_DIR / "distilled" / "sessions"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
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


def list_project_sessions(project_path, min_size_kb=100):
    """List session files in project directory"""
    if not project_path or not project_path.exists():
        return []

    sessions = []
    for session_file in project_path.glob("*.jsonl"):
        size_kb = session_file.stat().st_size / 1024
        if size_kb >= min_size_kb:
            sessions.append({
                "path": session_file,
                "size": f"{size_kb:.1f}KB",
                "lines": len(session_file.read_text().splitlines()),
                "mtime": datetime.fromtimestamp(session_file.stat().st_mtime).strftime("%Y-%m-%d"),
                "name": session_file.name
            })

    return sorted(sessions, key=lambda x: x["mtime"], reverse=True)


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

    sessions = list_project_sessions(project_path, min_size_kb=0)
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


def select_turns_for_packet(turns, max_turns=12):
    """Keep the opening request and the ending resolution for long sessions."""
    total = len(turns)
    if total <= max_turns:
        return turns, 0

    head_count = max_turns // 2
    tail_count = max_turns - head_count
    selected = turns[:head_count] + turns[-tail_count:]
    omitted = total - len(selected)
    return selected, omitted


def parse_jsonl_session(session_path):
    """Parse Claude Code .jsonl session file"""
    turns = []
    current_turn = None

    try:
        with open(session_path, 'r', encoding='utf-8-sig', errors='replace') as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue

                record_type = record.get('type')

                # User message
                if record_type == 'user':
                    message_content = record.get('message', {}).get('content', '')
                    if isinstance(message_content, str) and message_content and not message_content.startswith('<'):
                        current_turn = {
                            'user': message_content[:1000],
                            'assistant': [],
                            'tools': []
                        }
                        turns.append(current_turn)

                # Assistant message
                elif record_type == 'assistant' and current_turn:
                    message = record.get('message', {})
                    content = message.get('content', [])

                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict):
                                # Text response
                                if item.get('type') == 'text':
                                    text = item.get('text', '')
                                    if text and len(text) > 20:
                                        current_turn['assistant'].append(text[:800])

                                # Tool use
                                elif item.get('type') == 'tool_use':
                                    tool_name = item.get('name', '')
                                    tool_input = item.get('input', {})
                                    if tool_name:
                                        current_turn['tools'].append({
                                            'name': tool_name,
                                            'input': str(tool_input)[:200]
                                        })
    except Exception as e:
        print(f"Warning: Error parsing session: {e}")

    return turns


def generate_packet(session, packet_path):
    """Generate a packet file with actual session content"""
    session_path = Path(session['file_path'])
    all_turns = parse_jsonl_session(session_path)
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
        "2. Query claude-mem for dedup",
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

    sessions = list_project_sessions(project_path, min_size)
    if not sessions:
        print(f"No sessions found larger than {min_size}KB")
        return

    print(f"{'Size':<8} {'Lines':<6} {'Modified':<12} Filename")
    print("-" * 60)
    for session in sessions:
        print(f"{session['size']:<8} {session['lines']:<6} {session['mtime']:<12} {session['name']}")


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
    parser.add_argument("command", nargs="?", choices=["run", "status", "list", "mark", "help"], default="help")
    parser.add_argument("--project", help="Project name")
    parser.add_argument("--next", type=int, default=DEFAULT_RUN_NEXT, help="Number of pending sessions to bundle for run")
    parser.add_argument("--size", type=int, default=DEFAULT_LIST_MIN_SIZE_KB, help="Minimum session size in KB for list")
    parser.add_argument("--force", action="store_true", help="Force regeneration")
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
