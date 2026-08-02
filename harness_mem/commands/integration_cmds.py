"""Handlers for the ``harness-mem integration`` maintenance subcommands.

The hook sync handler is the operator repair boundary: it repairs project hooks
and user-level Daily commands, emits one structured report, and returns a
nonzero exit code when any independently executed stage fails.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from harness_mem.integration.command_sync import (
    COMMAND_HOSTS,
    VALID_COMMAND_PROFILES,
    command_hint,
    known_command_names,
    resolve_command_names,
    sync_host_commands,
    sync_slash_commands,
)
from harness_mem.integration.installer import verified_hook_runner as verified_hook_runner
from harness_mem.integration.repair import repair_integrations
from harness_mem.transcript_evidence import (
    EVIDENCE_CLIENTS,
    collect_transcript_evidence,
    render_transcript_evidence,
)

__all__ = [
    "SUPPORTED_HOOK_CLIENTS",
    "cmd_install_hook_suite",
    "cmd_list_command_profiles",
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
    """Resolve ``--project-root`` to an absolute path (default: cwd)."""
    if project_root is None:
        return Path(os.getcwd())
    return Path(project_root).resolve()


def _install_suite(client: str, project_root: str | None, force: bool) -> int:
    root = _resolve_project_root(project_root)
    clients = COMMAND_HOSTS if client == "all" else (client,)
    report = repair_integrations(
        clients=clients,  # type: ignore[arg-type]
        project_root=root,
        force=force,
        hook_runner_provider=verified_hook_runner,
    )
    payload = report.to_dict()
    payload["messages"] = [
        f"{result.status}: {artifact}"
        for result in report.results
        if result.stage == "hooks" and result.status in {"installed", "updated"}
        for artifact in result.artifacts
    ]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if any(result.status == "failed" for result in report.results) else 0


def cmd_install_hook_suite(client: str, project_root: str | None, force: bool) -> int:
    """Repair hooks and Daily commands for one host or all supported hosts."""
    return _install_suite(client, project_root, force)


def cmd_transcript_evidence(client: str, project_root: str | None) -> int:
    """Print factual local transcript evidence for host adapters."""

    root = _resolve_project_root(project_root)
    clients = EVIDENCE_CLIENTS if client == "all" else (client,)
    reports = collect_transcript_evidence(root, clients=clients)
    print(render_transcript_evidence(reports))
    return 0


def cmd_list_command_profiles() -> int:
    """Print the available Daily slash command set."""

    print("Daily command actions:")
    for profile in VALID_COMMAND_PROFILES:
        commands = " ".join(f"/hm:{name}" for name in resolve_command_names(profile=profile))
        print(f"  {profile}: {commands}")
    print("")
    print("Host-native invocation:")
    for client in COMMAND_HOSTS:
        print(f"  {client}: {command_hint(client)}")
    print("")
    print("Known Daily actions:")
    print("  " + " ".join(f"hm-{name}" for name in known_command_names()))
    return 0


def _path_arg(value: str | None) -> Path | None:
    return Path(value).expanduser().resolve() if value else None


def _print_sync_result(result) -> int:
    prefix = "[DRY-RUN] Would sync" if result.dry_run else "Synced"
    commands = " ".join(f"/hm:{name}" for name in result.selected_commands)
    print(f"{prefix} {len(result.selected_commands)} Claude Code slash commands to {result.destination_dir}")
    print(f"  Available: {commands}")
    if result.removed_commands:
        removed = " ".join(f"/hm:{name}" for name in result.removed_commands)
        print(f"  Removed: {removed}")
    return 0


def cmd_sync_commands(
    *,
    profile: str,
    include: list[str] | None,
    source_dir: str | None,
    target_dir: str | None,
    client: str,
    project_root: str | None,
    scope: str,
    dry_run: bool,
) -> int:
    """Synchronize host-native Daily commands without reinstalling runtime."""

    try:
        if target_dir is not None and client == "all":
            # Backward compatibility: --target-dir has always meant a Claude
            # command directory, while the new default client is all.
            client = "claude-code"
        if target_dir is not None and client != "claude-code":
            raise ValueError("--target-dir is only supported with --client claude-code")
        if client == "all" and scope != "user":
            raise ValueError("--client all supports only --scope user")
        if client == "claude-code" and target_dir is not None:
            result = sync_slash_commands(
                source_dir=_path_arg(source_dir),
                destination_dir=_path_arg(target_dir),
                profile=profile,
                include=include or [],
                dry_run=dry_run,
            )
        else:
            if include:
                raise ValueError("optional slash command groups were removed; sync daily only")
            clients = COMMAND_HOSTS if client == "all" else (client,)
            results = [
                sync_host_commands(
                    client=item,  # type: ignore[arg-type]
                    project_root=_resolve_project_root(project_root),
                    scope=scope,  # type: ignore[arg-type]
                    source_dir=_path_arg(source_dir),
                    dry_run=dry_run,
                )
                for item in clients
            ]
            result = results[0]
    except (FileNotFoundError, ValueError) as exc:
        print(f"command sync failed: {exc}", file=sys.stderr)
        return 1
    if client == "all" and target_dir is None:
        prefix = "[DRY-RUN] Would sync" if dry_run else "Synced"
        for item, item_result in zip(COMMAND_HOSTS, results):
            print(
                f"{prefix} {len(item_result.selected_commands)} {item} Daily commands "
                f"to {item_result.destination_dir}"
            )
        return 0

    prefix = "[DRY-RUN] Would sync" if result.dry_run else "Synced"
    if client == "claude-code":
        actions = " ".join(f"/hm:{name}" for name in result.selected_commands)
    elif client == "codex":
        actions = " ".join(f"$hm-{name}" for name in result.selected_commands)
    else:
        actions = " ".join(f"/hm-{name}" for name in result.selected_commands)
    print(f"{prefix} {len(result.selected_commands)} {client} Daily commands to {result.destination_dir}")
    print(f"  Available: {actions}")
    return 0
