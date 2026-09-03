"""Handlers for explicit host integration repair."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from harness_mem.integration.command_sync import (
    COMMAND_HOSTS,
    command_hint,
    sync_host_commands,
)
from harness_mem.integration.installer import verified_hook_runner as verified_hook_runner
from harness_mem.integration.repair import repair_project_hooks
from harness_mem.transcript_evidence import (
    EVIDENCE_CLIENTS,
    collect_transcript_evidence,
    render_transcript_evidence,
)

__all__ = [
    "SUPPORTED_HOOK_CLIENTS",
    "cmd_install_hook_suite",
    "cmd_list_commands",
    "cmd_sync_commands",
    "cmd_transcript_evidence",
]

SUPPORTED_HOOK_CLIENTS = (
    "cursor",
    "claude-code",
    "grok",
    "codex",
    "hermes",
    "opencode",
    "antigravity",
)


def _resolve_project_root(project_root: str | None) -> Path:
    return Path(os.getcwd()) if project_root is None else Path(project_root).resolve()


def cmd_install_hook_suite(client: str, project_root: str | None, force: bool) -> int:
    """Repair project Hooks for one host or all supported hosts."""

    clients = COMMAND_HOSTS if client == "all" else (client,)
    report = repair_project_hooks(
        clients=clients,  # type: ignore[arg-type]
        project_root=_resolve_project_root(project_root),
        force=force,
        hook_runner_provider=verified_hook_runner,
    )
    payload = report.to_dict()
    payload["messages"] = [
        f"{result.status}: {artifact}"
        for result in report.results
        if result.status in {"installed", "updated"}
        for artifact in result.artifacts
    ]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if any(result.status == "failed" for result in report.results) else 0


def cmd_transcript_evidence(client: str, project_root: str | None) -> int:
    """Print factual local transcript evidence for host adapters."""

    root = _resolve_project_root(project_root)
    clients = EVIDENCE_CLIENTS if client == "all" else (client,)
    reports = collect_transcript_evidence(root, clients=clients)
    print(render_transcript_evidence(reports))
    return 0


def cmd_list_commands() -> int:
    """Print the single global memory entry for every supported host."""

    print("Global memory entry:")
    for client in COMMAND_HOSTS:
        print(f"  {client}: {command_hint(client)}")
    return 0


def cmd_sync_commands(
    *,
    client: str,
    dry_run: bool,
    source_dir: str | None = None,
) -> int:
    """Synchronize the single user-level memory entry."""

    resolved_source = Path(source_dir).expanduser().resolve() if source_dir else None
    try:
        clients = COMMAND_HOSTS if client == "all" else (client,)
        results = [
            sync_host_commands(
                client=item,  # type: ignore[arg-type]
                source_dir=resolved_source,
                dry_run=dry_run,
            )
            for item in clients
        ]
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"command sync failed: {exc}", file=sys.stderr)
        return 1

    prefix = "[DRY-RUN] Would sync" if dry_run else "Synced"
    for item, result in zip(clients, results):
        print(f"{prefix} {item} entry to {result.destination_dir}")
        print(f"  Use: {command_hint(item)}")  # type: ignore[arg-type]
        if result.removed_commands:
            print(f"  Removed {len(result.removed_commands)} old entries")
    return 0
