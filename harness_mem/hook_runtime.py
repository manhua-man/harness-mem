"""Hook runtime diagnostics for generated IDE integrations."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_PROBE_CODE = r"""
import json
import sys
import harness_mem

print(json.dumps({
    "executable": sys.executable,
    "python_version": sys.version.split()[0],
    "harness_mem_version": harness_mem.__version__,
}))
"""


@dataclass(frozen=True)
class HookFileStatus:
    """Status for one known generated hook artifact."""

    client: str
    label: str
    path: Path
    exists: bool
    contains_host_entry: bool
    project_root_match: bool
    scope: str = "project"


@dataclass(frozen=True)
class PythonRuntimeProbe:
    """Result of probing whether a Python command can import harness_mem."""

    command: tuple[str, ...]
    ok: bool
    executable: str | None = None
    python_version: str | None = None
    harness_mem_version: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class HookRuntimeReport:
    """Doctor-friendly hook runtime report."""

    project_root: Path
    python_probe: PythonRuntimeProbe
    hooks: tuple[HookFileStatus, ...]
    ide_env_note: str = (
        "Probe uses the current shell environment; IDE hooks may see a different PATH/env."
    )


Runner = Callable[..., subprocess.CompletedProcess[str]]


def collect_hook_runtime_report(
    project_root: Path,
    *,
    python_command: Sequence[str] = ("python",),
    runner: Runner = subprocess.run,
    timeout_seconds: float = 5.0,
    home_dir: Path | None = None,
) -> HookRuntimeReport:
    """Collect hook files plus a current-shell Python import probe."""

    root = project_root.expanduser().resolve()
    return HookRuntimeReport(
        project_root=root,
        python_probe=probe_python_runtime(
            python_command=python_command,
            runner=runner,
            timeout_seconds=timeout_seconds,
        ),
        hooks=tuple(_known_hook_statuses(root, home_dir=home_dir)),
    )


def probe_python_runtime(
    *,
    python_command: Sequence[str] = ("python",),
    runner: Runner = subprocess.run,
    timeout_seconds: float = 5.0,
) -> PythonRuntimeProbe:
    """Probe whether ``python_command`` can import harness_mem."""

    command = tuple(python_command)
    try:
        completed = runner(
            [*command, "-c", _PROBE_CODE],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        return PythonRuntimeProbe(command=command, ok=False, error=str(exc))
    except subprocess.TimeoutExpired:
        return PythonRuntimeProbe(
            command=command,
            ok=False,
            error=f"timed out after {timeout_seconds:g}s",
        )
    except OSError as exc:
        return PythonRuntimeProbe(command=command, ok=False, error=str(exc))

    stdout = (completed.stdout or "").strip()
    stderr = _tail((completed.stderr or "").strip())
    if completed.returncode != 0:
        return PythonRuntimeProbe(
            command=command,
            ok=False,
            error=stderr or f"exit status {completed.returncode}",
        )

    try:
        payload = json.loads(stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return PythonRuntimeProbe(
            command=command,
            ok=False,
            error=f"invalid probe output: {exc}",
        )

    return PythonRuntimeProbe(
        command=command,
        ok=True,
        executable=_str_or_none(payload.get("executable")),
        python_version=_str_or_none(payload.get("python_version")),
        harness_mem_version=_str_or_none(payload.get("harness_mem_version")),
    )


def _known_hook_statuses(project_root: Path, *, home_dir: Path | None) -> list[HookFileStatus]:
    specs = [
        ("cursor", "session-start", project_root / ".cursor" / "hooks" / "session-start.sh", "project"),
        ("cursor", "after-agent", project_root / ".cursor" / "hooks" / "after-agent.sh", "project"),
        ("claude-code", "session-start", project_root / ".claude" / "hooks" / "session-start.sh", "project"),
        ("claude-code", "after-turn", project_root / ".claude" / "hooks" / "after-turn.sh", "project"),
        ("grok", "hooks manifest", project_root / ".grok" / "hooks" / "harness-mem.json", "project"),
        ("codex", "hooks manifest", project_root / ".codex" / "hooks.json", "project"),
        ("codex", "stop script", project_root / ".codex" / "hooks" / "harness_mem_stop.py", "project"),
        ("opencode", "plugin", project_root / ".opencode" / "plugins" / "harness-mem.ts", "project"),
    ]
    home = Path.home() if home_dir is None else home_dir
    specs.extend(
        [
            ("hermes", "pre_llm_call script", home / ".hermes" / "agent-hooks" / "harness_mem_pre_llm_call.py", "global"),
            ("hermes", "post_llm_call script", home / ".hermes" / "agent-hooks" / "harness_mem_post_llm_call.py", "global"),
            ("hermes", "config", home / ".hermes" / "config.yaml", "global"),
        ]
    )
    return [
        _hook_file_status(
            client=client,
            label=label,
            path=path,
            project_root=project_root,
            scope=scope,
        )
        for client, label, path, scope in specs
    ]


def _hook_file_status(
    *,
    client: str,
    label: str,
    path: Path,
    project_root: Path,
    scope: str,
) -> HookFileStatus:
    exists = path.exists()
    text = ""
    if exists and path.is_file():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    return HookFileStatus(
        client=client,
        label=label,
        path=path,
        exists=exists,
        contains_host_entry="harness_mem.host_entry" in text,
        project_root_match=project_root.as_posix() in text,
        scope=scope,
    )


def _tail(text: str, *, max_lines: int = 3) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-max_lines:])


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


__all__ = [
    "HookFileStatus",
    "HookRuntimeReport",
    "PythonRuntimeProbe",
    "collect_hook_runtime_report",
    "probe_python_runtime",
]
