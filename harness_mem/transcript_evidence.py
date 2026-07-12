"""Local transcript evidence discovery for host adapters."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from harness_mem.adapters import AdapterRegistry


EVIDENCE_CLIENTS = ("grok", "hermes", "opencode")


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
            reports.append(_opencode_evidence(home))
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
    sample_files = _hermes_session_files(sessions_root, sample_limit=sample_limit)
    all_files = _hermes_session_files(sessions_root, sample_limit=None)
    status = "verified_transcript_path" if all_files else _status_for_roots((sessions_root,))
    note = (
        "Found Hermes session_*.json files with session_id and messages[]."
        if all_files
        else (
            "Hermes sessions root exists, but no session_*.json file with transcript schema was found."
            if sessions_root.exists()
            else "Hermes sessions root was not found on this machine."
        )
    )
    return TranscriptEvidence(
        client="hermes",
        status=status,
        adapter_available="hermes" in AdapterRegistry.list(),
        roots=(sessions_root,),
        session_count=len(all_files),
        sample_files=tuple(sample_files),
        note=note,
    )


def _opencode_evidence(home: Path) -> TranscriptEvidence:
    roots = _opencode_roots(home)
    status = _status_for_roots(roots)
    if any(root.exists() for root in roots):
        note = (
            "OpenCode root/config exists, but no verified transcript path/schema was found. "
            "Do not treat this host as ingest-ready yet."
        )
    else:
        note = "No known OpenCode root was found on this machine."
    return TranscriptEvidence(
        client="opencode",
        status=status,
        adapter_available="opencode" in AdapterRegistry.list(),
        roots=roots,
        note=note,
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
    if not isinstance(data.get("session_id"), str) or not data["session_id"].strip():
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
