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
from harness_mem.integration.installer import install_hook

__all__ = [
    "cmd_install_cursor_hook",
    "cmd_install_claude_hook",
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


def cmd_install_cursor_hook(project_root: str | None, force: bool) -> int:
    """Generate the Cursor after-agent hook script.

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
    """Generate the Claude Code after-turn hook script.

    Resolves ``project_root`` (default: cwd), targets
    ``<project_root>/.claude/hooks/after-turn.sh``, and delegates to
    :func:`install_hook`. Shares the exit/diagnostic shape with
    :func:`cmd_install_cursor_hook`.
    """
    root = _resolve_project_root(project_root)
    target_path = root / ".claude" / "hooks" / "after-turn.sh"
    return _install("claude_code_hook.sh.template", target_path, root, force)
