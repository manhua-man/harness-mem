"""Local transcript evidence discovery for host adapters."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from harness_mem.adapters import AdapterRegistry
from harness_mem.adapters.antigravity.adapter import AntigravityAdapter
from harness_mem.adapters.hermes.adapter import HermesAdapter
from harness_mem.adapters.opencode.adapter import OpenCodeAdapter


EVIDENCE_CLIENTS = ("grok", "hermes", "opencode", "antigravity")


@dataclass(frozen=True)
class TranscriptEvidence:
    """Evidence summary for one host transcript source."""

    client: str
    status: str
    adapter_available: bool
    roots: tuple[Path, ...]
    session_count: int = 0
    sample_files: tuple[Path, ...] = ()
    note: str = ""


def collect_transcript_evidence(
    project_root: Path,
    *,
    clients: Sequence[str] = EVIDENCE_CLIENTS,
    home_dir: Path | None = None,
    sample_limit: int = 3,
) -> tuple[TranscriptEvidence, ...]:
    """Collect factual local evidence for host transcript adapters."""

    home = Path.home() if home_dir is None else home_dir
    root = project_root.expanduser().resolve()
    reports: list[TranscriptEvidence] = []
    for client in clients:
        normalized = client.strip().lower()
        if normalized == "grok":
            reports.append(_grok_evidence(root, home, sample_limit=sample_limit))
        elif normalized == "hermes":
            reports.append(_hermes_evidence(home, sample_limit=sample_limit))
        elif normalized == "opencode":
            reports.append(_opencode_evidence(home, root))
        elif normalized == "antigravity":
            reports.append(_antigravity_evidence(home, root, sample_limit=sample_limit))
        else:
            reports.append(
                TranscriptEvidence(
                    client=normalized,
                    status="unsupported_client",
                    adapter_available=normalized in AdapterRegistry.list(),
                    roots=(),
                    note="No evidence scanner is registered for this client.",
                )
            )
    return tuple(reports)


def render_transcript_evidence(reports: Iterable[TranscriptEvidence]) -> str:
    """Render transcript evidence in a CLI-friendly text block."""

    lines = ["Transcript evidence:"]
    for report in reports:
        adapter = "available" if report.adapter_available else "unavailable"
        lines.append(f"  {report.client}: {report.status} | adapter={adapter}")
        for root in report.roots:
            exists = "exists" if root.exists() else "missing"
            lines.append(f"    root: {root.as_posix()} ({exists})")
        if report.session_count:
            lines.append(f"    sessions: {report.session_count}")
        for sample in report.sample_files:
            lines.append(f"    sample: {sample.as_posix()}")
        if report.note:
            lines.append(f"    note: {report.note}")
    return "\n".join(lines)


def _grok_evidence(project_root: Path, home: Path, *, sample_limit: int) -> TranscriptEvidence:
    sessions_root = home / ".grok" / "sessions"
    project_bucket = sessions_root / _grok_project_bucket(project_root)
    sample_files = _grok_chat_history_files(project_bucket, sample_limit=sample_limit)
    status = "verified_transcript_path" if sample_files else "missing"
    note = (
        "Found chat_history.jsonl under Grok's URL-encoded project-root bucket."
        if sample_files
        else "No Grok chat_history.jsonl files found for this project root."
    )
    return TranscriptEvidence(
        client="grok",
        status=status,
        adapter_available="grok" in AdapterRegistry.list(),
        roots=(project_bucket,),
        session_count=len(_grok_chat_history_files(project_bucket, sample_limit=None)),
        sample_files=tuple(sample_files),
        note=note,
    )


def _hermes_evidence(home: Path, *, sample_limit: int) -> TranscriptEvidence:
    sessions_root = home / ".hermes" / "sessions"
    state_db_candidates = (
        home / "AppData" / "Local" / "hermes" / "state.db",
        home / ".hermes" / "state.db",
    )
    state_db = next((path for path in state_db_candidates if path.is_file()), None)
    adapter = HermesAdapter(
        None,
        sessions_dir=sessions_root,
        state_db=state_db,
        scope="all",
    )
    db_sessions = [
        session
        for session in adapter.list_sessions(min_size_kb=0)
        if session.get("source_kind") == "sqlite-session-export"
    ]
    all_files = _hermes_session_files(sessions_root, sample_limit=None)
    sample_files = [*all_files, *(Path(session["path"]) for session in db_sessions)]
    sample_files = list(dict.fromkeys(sample_files))[:sample_limit]
    roots = (sessions_root, *state_db_candidates)
    status = (
        "verified_transcript_path"
        if all_files or db_sessions
        else _status_for_roots(roots)
    )
    note = (
        "Found Hermes state.db sessions/messages rows."
        if db_sessions
        else "Found Hermes session_*.json files with session_id and messages[]."
        if all_files
        else (
            "Hermes roots exist, but no verified JSON or SQLite transcript schema was found."
            if any(root.exists() for root in roots)
            else "Hermes JSON sessions and state.db were not found on this machine."
        )
    )
    return TranscriptEvidence(
        client="hermes",
        status=status,
        adapter_available="hermes" in AdapterRegistry.list(),
        roots=roots,
        session_count=len(all_files) + len(db_sessions),
        sample_files=tuple(sample_files),
        note=note,
    )


def _opencode_evidence(home: Path, project_root: Path) -> TranscriptEvidence:
    roots = _opencode_roots(home)
    adapter = OpenCodeAdapter(None, home_dir=home, project_root=project_root)
    database = adapter.database_path
    sessions = adapter.list_sessions() if database else []
    status = "verified_transcript_path" if sessions else _status_for_roots(roots)
    return TranscriptEvidence(
        client="opencode",
        status=status,
        adapter_available="opencode" in AdapterRegistry.list(),
        roots=tuple(dict.fromkeys((*roots, database.parent) if database else roots)),
        session_count=len(sessions),
        sample_files=(database,) if database else (),
        note=(
            "Found OpenCode SQLite session/message/part tables for this project."
            if sessions
            else (
                "No known OpenCode root was found on this machine."
                if not any(root.exists() for root in roots)
                else "no verified transcript path/schema: readable OpenCode SQLite session database was not found for this project."
            )
        ),
    )


def _antigravity_evidence(
    home: Path,
    project_root: Path,
    *,
    sample_limit: int,
) -> TranscriptEvidence:
    brain_root = home / ".gemini" / "antigravity" / "brain"
    cli_root = home / ".gemini" / "antigravity-cli"
    adapter = AntigravityAdapter(
        None,
        brain_dir=brain_root,
        cli_root=cli_root,
        project_root=project_root,
    )
    sessions = adapter.list_sessions(limit=None)
    roots = (brain_root, cli_root)
    status = "verified_transcript_path" if sessions else _status_for_roots(roots)
    return TranscriptEvidence(
        client="antigravity",
        status=status,
        adapter_available="antigravity" in AdapterRegistry.list(),
        roots=roots,
        session_count=len(sessions),
        sample_files=tuple(Path(item["path"]) for item in sessions[:sample_limit]),
        note=(
            "Found project-matched Antigravity brain transcript or CLI history evidence."
            if sessions
            else "No Antigravity brain transcript or CLI history matched this project."
        ),
    )


def _status_for_roots(roots: Sequence[Path]) -> str:
    return "insufficient_evidence" if any(root.exists() for root in roots) else "missing"


def _grok_project_bucket(project_root: Path) -> str:
    return quote(str(project_root), safe="")


def _grok_chat_history_files(project_bucket: Path, *, sample_limit: int | None) -> list[Path]:
    if not project_bucket.exists() or not project_bucket.is_dir():
        return []
    files = [
        path
        for path in project_bucket.glob("*/chat_history.jsonl")
        if path.is_file() and path.stat().st_size > 0
    ]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    if sample_limit is None:
        return files
    return files[:sample_limit]


def _hermes_session_files(sessions_root: Path, *, sample_limit: int | None) -> list[Path]:
    if not sessions_root.exists() or not sessions_root.is_dir():
        return []
    files = [
        path
        for path in sessions_root.glob("session_*.json")
        if path.is_file() and path.stat().st_size > 0 and _is_hermes_session_file(path)
    ]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    if sample_limit is None:
        return files
    return files[:sample_limit]


def _is_hermes_session_file(path: Path) -> bool:
    data = _read_json_object(path)
    if data is None:
        return False
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return False
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        return False
    return any(_is_transcript_message(message) for message in messages)


def _opencode_roots(home: Path) -> tuple[Path, ...]:
    return (
        home / ".opencode",
        home / ".config" / "opencode",
        home / "AppData" / "Roaming" / "opencode",
        home / "AppData" / "Local" / "opencode",
        home / "AppData" / "Roaming" / "OpenCode",
        home / "AppData" / "Local" / "OpenCode",
    )


def _is_transcript_message(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    role = value.get("role") or value.get("type")
    if not isinstance(role, str) or not role.strip():
        return False
    return any(key in value and value[key] not in (None, "") for key in ("content", "text", "message"))


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


__all__ = [
    "EVIDENCE_CLIENTS",
    "TranscriptEvidence",
    "collect_transcript_evidence",
    "render_transcript_evidence",
]
