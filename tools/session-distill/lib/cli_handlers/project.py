"""Project/session preparation command handlers for session-distill."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from lib.packet import packet_audit_from_jsonl_file, render_session_packet_markdown
from lib.parser import list_session_files, parse_claude_jsonl_session

EnsureDirs = Callable[[], None]
LoadManifest = Callable[[], dict[str, Any]]
SaveManifest = Callable[[dict[str, Any]], None]
SourceSignature = Callable[[dict[str, Any]], dict[str, Any]]
T = TypeVar("T")

MANIFEST_FILE: Path | None = None
PACKETS_DIR: Path | None = None
DEFAULT_RUN_NEXT = 3

_ensure_dirs: EnsureDirs | None = None
_load_manifest: LoadManifest | None = None
_save_manifest: SaveManifest | None = None
_source_signature: SourceSignature | None = None


def configure(
    *,
    manifest_file: Path,
    packets_dir: Path,
    default_run_next: int,
    ensure_dirs: EnsureDirs,
    load_manifest: LoadManifest,
    save_manifest: SaveManifest,
    source_signature: SourceSignature,
) -> None:
    """Bind CLI-owned paths and helpers before executing a project command."""
    global MANIFEST_FILE, PACKETS_DIR, DEFAULT_RUN_NEXT
    global _ensure_dirs, _load_manifest, _save_manifest, _source_signature
    MANIFEST_FILE = manifest_file
    PACKETS_DIR = packets_dir
    DEFAULT_RUN_NEXT = default_run_next
    _ensure_dirs = ensure_dirs
    _load_manifest = load_manifest
    _save_manifest = save_manifest
    _source_signature = source_signature


def _configured_path(value: Path | None, name: str) -> Path:
    if value is None:
        raise RuntimeError(f"project handler is not configured: {name}")
    return value


def _configured_callable(value: T | None, name: str) -> T:
    if value is None:
        raise RuntimeError(f"project handler is not configured: {name}")
    return value


def cmd_index(project_path: Optional[Path]) -> int:
    """Index sessions."""
    ensure_dirs = _configured_callable(_ensure_dirs, "ensure_dirs")
    load_manifest = _configured_callable(_load_manifest, "load_manifest")
    save_manifest = _configured_callable(_save_manifest, "save_manifest")
    source_signature = _configured_callable(_source_signature, "source_signature")

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
    ensure_dirs = _configured_callable(_ensure_dirs, "ensure_dirs")
    load_manifest = _configured_callable(_load_manifest, "load_manifest")
    save_manifest = _configured_callable(_save_manifest, "save_manifest")
    packets_dir = _configured_path(PACKETS_DIR, "packets_dir")

    print("==> Bundle: Generating packets")
    ensure_dirs()
    manifest = load_manifest()
    count = 0

    target_count = next_count if next_count is not None and next_count > 0 else None

    for session in pending_sessions(manifest):
        if target_count is not None and count >= target_count:
            break

        session_id = session["session_id"]
        packet_path = packets_dir / f"{session_id}.md"

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
    manifest_file = _configured_path(MANIFEST_FILE, "manifest_file")
    load_manifest = _configured_callable(_load_manifest, "load_manifest")

    print("==> Session Distiller Status")
    print("")

    if not manifest_file.exists():
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

    print("Durable knowledge: harness-mem candidate review lifecycle")
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


def cmd_run(
    project_path: Optional[Path],
    force: bool = False,
    next_count: int = DEFAULT_RUN_NEXT,
) -> int:
    """Run preparation phase."""
    ensure_dirs = _configured_callable(_ensure_dirs, "ensure_dirs")

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
    print("  2. AI extracts candidate drafts from session evidence")
    print("  3. AI exports candidates through harness-mem suggest_* tools")
    print("  4. User/agent invokes /hm:review for durable memory")
    print("  5. Optionally update distilled session notes for archive context")
    print("")

    return cmd_status(project_path)
