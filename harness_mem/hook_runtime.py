"""Runtime diagnostics for generated IDE hook integrations."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from harness_mem.integration.hook_runner import HookRunnerProbe, probe_hook_runner

__all__ = [
    "HookFileStatus",
    "HookRunnerProbe",
    "HookRuntimeReport",
    "collect_hook_file_statuses",
    "collect_hook_runtime_report",
    "probe_hook_runner",
]

_LEGACY_HOST_ENTRY = "harness_mem.host_entry"
Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class HookFileStatus:
    """Status for one known generated hook artifact."""

    client: str
    label: str
    path: Path
    exists: bool
    runner_bound: bool
    legacy_python: bool
    project_root_match: bool
    scope: str = "project"


@dataclass(frozen=True)
class HookRuntimeReport:
    """Doctor-friendly status of the installed Hook runner and its artifacts."""

    project_root: Path
    runner_probe: HookRunnerProbe
    hooks: tuple[HookFileStatus, ...]


def collect_hook_runtime_report(
    project_root: Path,
    *,
    hook_runner: Path | None = None,
    runner: Runner = subprocess.run,
    timeout_seconds: float = 5.0,
    home_dir: Path | None = None,
) -> HookRuntimeReport:
    """Collect generated Hook artifacts and probe the exact bound runner."""

    root = project_root.expanduser().resolve()
    runner_probe = probe_hook_runner(
        hook_runner=hook_runner,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    return HookRuntimeReport(
        project_root=root,
        runner_probe=runner_probe,
        hooks=tuple(
            _known_hook_statuses(
                root,
                home_dir=home_dir,
                hook_runner=runner_probe.path if runner_probe.ok else None,
            )
        ),
    )


def collect_hook_file_statuses(
    project_root: Path,
    *,
    client: str | None = None,
    home_dir: Path | None = None,
    hook_runner: Path | None = None,
) -> tuple[HookFileStatus, ...]:
    """Return known Hook artifacts without launching the runner probe."""

    root = project_root.expanduser().resolve()
    statuses = _known_hook_statuses(root, home_dir=home_dir, hook_runner=hook_runner)
    if client is not None:
        statuses = [status for status in statuses if status.client == client]
    return tuple(statuses)


def _known_hook_statuses(
    project_root: Path,
    *,
    home_dir: Path | None,
    hook_runner: Path | None,
) -> list[HookFileStatus]:
    specs = [
        ("cursor", "session-start", project_root / ".cursor" / "hooks" / "session-start.sh", "project"),
        ("cursor", "after-agent", project_root / ".cursor" / "hooks" / "after-agent.sh", "project"),
        ("claude-code", "session-start", project_root / ".claude" / "hooks" / "session-start.sh", "project"),
        ("claude-code", "after-turn", project_root / ".claude" / "hooks" / "after-turn.sh", "project"),
        ("grok", "hooks manifest", project_root / ".grok" / "hooks" / "harness-mem.json", "project"),
        ("codex", "hooks manifest", project_root / ".codex" / "hooks.json", "project"),
        ("opencode", "plugin", project_root / ".opencode" / "plugins" / "harness-mem.ts", "project"),
        ("antigravity", "hooks manifest", project_root / ".agents" / "hooks.json", "project"),
    ]
    home = Path.home() if home_dir is None else home_dir
    specs.append(("hermes", "config", home / ".hermes" / "config.yaml", "global"))
    return [
        _hook_file_status(
            client=client,
            label=label,
            path=path,
            project_root=project_root,
            scope=scope,
            hook_runner=hook_runner,
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
    hook_runner: Path | None,
) -> HookFileStatus:
    exists = path.exists()
    text = ""
    if exists and path.is_file():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    runner_path = hook_runner.as_posix() if hook_runner is not None else ""
    return HookFileStatus(
        client=client,
        label=label,
        path=path,
        exists=exists,
        runner_bound=bool(runner_path and runner_path in text),
        legacy_python=_LEGACY_HOST_ENTRY in text,
        project_root_match=project_root.as_posix() in text,
        scope=scope,
    )
