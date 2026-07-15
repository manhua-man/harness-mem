"""Resolve and probe the installed console entry used by generated hooks."""

from __future__ import annotations

import os
import shutil
import subprocess
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

__all__ = [
    "HookRunnerProbe",
    "resolve_hook_runner",
    "probe_hook_runner",
]

_HOOK_RUNNER = "harness-mem-hook"
_Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class HookRunnerProbe:
    """Result of verifying the console script bound into generated hooks."""

    path: Path | None
    ok: bool
    version: str | None = None
    error: str | None = None


def resolve_hook_runner() -> Path:
    """Return the absolute installed ``harness-mem-hook`` console script.

    The package installer creates console scripts beside the active Python
    environment. Looking there first avoids accidentally binding an unrelated
    executable found earlier on an IDE-specific ``PATH``.
    """

    scripts_dir = Path(sysconfig.get_path("scripts")).resolve()
    candidates = [scripts_dir / _HOOK_RUNNER]
    if os.name == "nt":
        candidates.extend(
            scripts_dir / f"{_HOOK_RUNNER}{suffix}"
            for suffix in (".exe", ".cmd", ".bat")
        )

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    discovered = shutil.which(_HOOK_RUNNER)
    if discovered:
        return Path(discovered).resolve()

    raise RuntimeError(
        "harness-mem-hook executable was not found; reinstall harness-mem "
        "before installing IDE hooks"
    )


def probe_hook_runner(
    *,
    hook_runner: Path | None = None,
    runner: _Runner = subprocess.run,
    timeout_seconds: float = 5.0,
) -> HookRunnerProbe:
    """Verify that the installed Hook entry executes and reports a version."""

    try:
        path = resolve_hook_runner() if hook_runner is None else Path(hook_runner).resolve()
    except RuntimeError as exc:
        return HookRunnerProbe(path=None, ok=False, error=str(exc))

    if not path.is_file():
        return HookRunnerProbe(path=path, ok=False, error="executable does not exist")

    try:
        completed = runner(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        return HookRunnerProbe(path=path, ok=False, error=str(exc))
    except subprocess.TimeoutExpired:
        return HookRunnerProbe(
            path=path,
            ok=False,
            error=f"timed out after {timeout_seconds:g}s",
        )
    except OSError as exc:
        return HookRunnerProbe(path=path, ok=False, error=str(exc))

    if completed.returncode != 0:
        detail = _tail(completed.stderr or completed.stdout or "")
        return HookRunnerProbe(
            path=path,
            ok=False,
            error=detail or f"exit status {completed.returncode}",
        )

    output = (completed.stdout or "").strip()
    prefix = f"{_HOOK_RUNNER} "
    if not output.startswith(prefix):
        return HookRunnerProbe(
            path=path,
            ok=False,
            error=f"unexpected --version output: {output!r}",
        )
    return HookRunnerProbe(path=path, ok=True, version=output[len(prefix) :].strip())


def _tail(text: str, *, max_lines: int = 3) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-max_lines:])
