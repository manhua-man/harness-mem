"""Handlers for explicit host integration repair."""

from __future__ import annotations

import json
import os
from pathlib import Path

from harness_mem.integration.installer import USER_HOOK_HOSTS as SUPPORTED_HOOK_CLIENTS
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
    "cmd_transcript_evidence",
]


def _resolve_project_root(project_root: str | None) -> Path:
    return Path(os.getcwd()) if project_root is None else Path(project_root).resolve()


def cmd_install_hook_suite(client: str, project_root: str | None, force: bool, *, scope: str = "project") -> int:
    """Repair native Hooks for one host or all supported hosts."""

    clients = SUPPORTED_HOOK_CLIENTS if client == "all" else (client,)
    report = repair_project_hooks(
        clients=clients,  # type: ignore[arg-type]
        project_root=_resolve_project_root(project_root),
        force=force,
        hook_runner_provider=verified_hook_runner,
        scope=scope,  # type: ignore[arg-type]
    )
    payload = report.to_dict()
    payload["messages"] = [
        f"{result.status}: {artifact}"
        for result in report.results
        if result.status in {"installed", "updated"}
        for artifact in result.artifacts
    ]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if report.success else 1


def cmd_transcript_evidence(client: str, project_root: str | None) -> int:
    """Print factual local transcript evidence for host adapters."""

    root = _resolve_project_root(project_root)
    clients = EVIDENCE_CLIENTS if client == "all" else (client,)
    reports = collect_transcript_evidence(root, clients=clients)
    print(render_transcript_evidence(reports))
    return 0
