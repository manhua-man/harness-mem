"""Local transcript evidence discovery for host adapters."""

from __future__ import annotations

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
    """Collect factual local evidence for unimplemented transcript adapters."""

    home = Path.home() if home_dir is None else home_dir
    root = project_root.expanduser().resolve()
    reports: list[TranscriptEvidence] = []
    for client in clients:
        normalized = client.strip().lower()
        if normalized == "grok":
            reports.append(_grok_evidence(root, home, sample_limit=sample_limit))
        elif normalized == "hermes":
            reports.append(_generic_missing_evidence("hermes", home / ".hermes"))
        elif normalized == "opencode":
            reports.append(_generic_missing_evidence("opencode", home / ".opencode"))
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


def _generic_missing_evidence(client: str, root: Path) -> TranscriptEvidence:
    status = "insufficient_evidence" if root.exists() else "missing"
    note = (
        "Host root exists, but no verified transcript path/schema is known yet."
        if root.exists()
        else "Host root was not found on this machine."
    )
    return TranscriptEvidence(
        client=client,
        status=status,
        adapter_available=client in AdapterRegistry.list(),
        roots=(root,),
        note=note,
    )


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


__all__ = [
    "EVIDENCE_CLIENTS",
    "TranscriptEvidence",
    "collect_transcript_evidence",
    "render_transcript_evidence",
]
