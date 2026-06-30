"""Handlers for the ``harness-mem integration`` maintenance subcommands.

These two handlers generate IDE hook scripts that invoke the host entry. They
are deliberately thin: both compute the IDE-specific
``target_path`` + ``template_name`` and delegate the rendering, boundary
self-check, and overwrite policy to
:func:`harness_mem.integration.installer.install_hook`.

Output contract: the generated file path and success confirmation go to stdout
via :func:`print`; diagnostics go to stderr. Exit codes are returned as ``int``
for the CLI dispatcher to propagate.

``FileExistsError`` is a subclass of ``OSError``, so the existing-hook case is
caught before the generic filesystem-error case to keep the two diagnostics
distinct (Req 5.5/5.7, Req 6.5/6.7).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from harness_mem import __version__
from harness_mem.integration.command_sync import (
    VALID_COMMAND_PROFILES,
    known_command_names,
    resolve_command_names,
    sync_slash_commands,
)
from harness_mem.integration.installer import HookSpec, install_hook, install_hook_suite

__all__ = [
    "cmd_install_cursor_hook",
    "cmd_install_claude_hook",
    "cmd_install_cursor_wake_hook",
    "cmd_install_claude_wake_hook",
    "cmd_install_hook_suite",
    "cmd_install_cursor_suite",
    "cmd_install_claude_suite",
    "cmd_list_command_profiles",
    "cmd_sync_commands",
]

# Canonical operator-facing doc the generated hook headers point at.
_DOC_POINTER = "docs/quickstart.md"


def _resolve_project_root(project_root: str | None) -> Path:
    """Resolve ``--project-root`` to an absolute path (default: cwd)."""
    if project_root is None:
        return Path(os.getcwd())
    return Path(project_root).resolve()


def _install(template_name: str, target_path: Path, root: Path, force: bool) -> int:
    """Render+write a hook, mapping installer exceptions to the exit contract."""
    try:
        written = install_hook(
            template_name=template_name,
            target_path=target_path,
            project_root=root,
            force=force,
            harness_mem_version=__version__,
            generated_at=datetime.now(timezone.utc),
            doc_pointer=_DOC_POINTER,
        )
    except FileExistsError:
        print(
            f"hook already exists: {target_path}; use --force to overwrite",
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(f"install failed: {target_path}: {exc}", file=sys.stderr)
        return 1
    print(f"installed: {written}")
    return 0


def _suite_specs(client: str, root: Path) -> tuple[HookSpec, ...]:
    if client == "cursor":
        return (
            HookSpec(
                "cursor_session_start.sh.template",
                root / ".cursor" / "hooks" / "session-start.sh",
            ),
            HookSpec(
                "cursor_after_agent.sh.template",
                root / ".cursor" / "hooks" / "after-agent.sh",
            ),
        )
    if client == "claude-code":
        return (
            HookSpec(
                "claude_code_session_start.sh.template",
                root / ".claude" / "hooks" / "session-start.sh",
            ),
            HookSpec(
                "claude_code_hook.sh.template",
                root / ".claude" / "hooks" / "after-turn.sh",
            ),
        )
    raise ValueError(f"unsupported hook client: {client}")


def _install_suite(client: str, project_root: str | None, force: bool) -> int:
    root = _resolve_project_root(project_root)
    try:
        results = install_hook_suite(
            specs=_suite_specs(client, root),
            project_root=root,
            force=force,
            harness_mem_version=__version__,
            generated_at=datetime.now(timezone.utc),
            doc_pointer=_DOC_POINTER,
        )
    except (OSError, ValueError) as exc:
        print(f"install failed: {root}: {exc}", file=sys.stderr)
        return 1
    for result in results:
        if result.status == "installed":
            print(f"installed: {result.target_path}")
        else:
            print(f"exists: {result.target_path}")
    return 0


def cmd_install_cursor_hook(project_root: str | None, force: bool) -> int:
    """Generate the Cursor post-turn hook script.

    Resolves ``project_root`` (default: cwd), targets
    ``<project_root>/.cursor/hooks/after-agent.sh``, and delegates to
    :func:`install_hook`. On success prints ``installed: <path>`` to stdout and
    exits 0; on an existing hook without ``--force`` or a filesystem error,
    emits a diagnostic to stderr and exits 1.
    """
    root = _resolve_project_root(project_root)
    target_path = root / ".cursor" / "hooks" / "after-agent.sh"
    return _install("cursor_after_agent.sh.template", target_path, root, force)


def cmd_install_claude_hook(project_root: str | None, force: bool) -> int:
    """Generate the Claude Code post-turn hook script.

    Resolves ``project_root`` (default: cwd), targets
    ``<project_root>/.claude/hooks/after-turn.sh``, and delegates to
    :func:`install_hook`. Shares the exit/diagnostic shape with
    :func:`cmd_install_cursor_hook`.
    """
    root = _resolve_project_root(project_root)
    target_path = root / ".claude" / "hooks" / "after-turn.sh"
    return _install("claude_code_hook.sh.template", target_path, root, force)


def cmd_install_cursor_wake_hook(project_root: str | None, force: bool) -> int:
    """Generate the Cursor session-start wake hook script."""
    root = _resolve_project_root(project_root)
    target_path = root / ".cursor" / "hooks" / "session-start.sh"
    return _install("cursor_session_start.sh.template", target_path, root, force)


def cmd_install_claude_wake_hook(project_root: str | None, force: bool) -> int:
    """Generate the Claude Code session-start wake hook script."""
    root = _resolve_project_root(project_root)
    target_path = root / ".claude" / "hooks" / "session-start.sh"
    return _install("claude_code_session_start.sh.template", target_path, root, force)


def cmd_install_cursor_suite(project_root: str | None, force: bool) -> int:
    """Generate Cursor wake + post-turn maintenance hooks."""
    return _install_suite("cursor", project_root, force)


def cmd_install_claude_suite(project_root: str | None, force: bool) -> int:
    """Generate Claude Code wake + post-turn maintenance hooks."""
    return _install_suite("claude-code", project_root, force)


def cmd_install_hook_suite(client: str, project_root: str | None, force: bool) -> int:
    """Generate the complete hook suite for one supported client."""
    return _install_suite(client, project_root, force)


def cmd_list_command_profiles() -> int:
    """Print the available Daily slash command set."""

    print("Claude Code slash commands:")
    for profile in VALID_COMMAND_PROFILES:
        commands = " ".join(f"/hm:{name}" for name in resolve_command_names(profile=profile))
        print(f"  {profile}: {commands}")
    print("")
    print("Known command files:")
    print("  " + " ".join(f"/hm:{name}" for name in known_command_names()))
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
    dry_run: bool,
) -> int:
    """Synchronize Claude Code slash commands without reinstalling runtime."""

    try:
        result = sync_slash_commands(
            source_dir=_path_arg(source_dir),
            destination_dir=_path_arg(target_dir),
            profile=profile,
            include=include or [],
            dry_run=dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"command sync failed: {exc}", file=sys.stderr)
        return 1
    return _print_sync_result(result)
