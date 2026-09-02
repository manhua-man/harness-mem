"""Unified operator repair for host hooks and memory command surfaces."""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from harness_mem import __version__
from harness_mem.integration.command_sync import (
    COMMAND_HOSTS,
    CommandHost,
    sync_host_commands,
)
from harness_mem.integration import installer
from harness_mem.integration.installer import HookInstallResult, HookSpec

RepairStage = Literal["hooks", "commands"]
RepairStatus = Literal["installed", "updated", "unchanged", "failed", "unsupported"]
OverallStatus = Literal["success", "partial_failure", "failed", "unsupported"]


@dataclass(frozen=True)
class RepairStageResult:
    """Outcome of one independently executed host repair stage."""

    host: CommandHost
    stage: RepairStage
    status: RepairStatus
    artifacts: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class IntegrationRepairReport:
    """Structured cross-host repair result suitable for CLI JSON output."""

    status: OverallStatus
    success: bool
    results: tuple[RepairStageResult, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _quote_command(*values: str) -> str:
    return " ".join(shlex.quote(value) for value in values)


def _host_entry_command(
    hook_runner: Path,
    action: str,
    root: Path,
    trigger_id: str,
    client: CommandHost,
) -> str:
    return _quote_command(
        hook_runner.as_posix(),
        "--action",
        action,
        "--project-root",
        root.resolve().as_posix(),
        "--source",
        "ide_hook",
        "--trigger-id",
        trigger_id,
        "--client",
        client,
    )


def _suite_specs(
    client: CommandHost, root: Path, hook_runner: Path
) -> tuple[HookSpec, ...]:
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
    if client == "grok":
        return (
            HookSpec(
                "grok_hooks.json.template",
                root / ".grok" / "hooks" / "harness-mem.json",
                template_vars={
                    "WAKE_COMMAND_JSON": json.dumps(
                        _host_entry_command(
                            hook_runner,
                            "wake-start",
                            root,
                            "grok-session-start",
                            client,
                        )
                    ),
                    "POST_TURN_COMMAND_JSON": json.dumps(
                        _host_entry_command(
                            hook_runner,
                            "post-turn-maintenance",
                            root,
                            "grok-stop",
                            client,
                        )
                    ),
                },
            ),
        )
    if client == "codex":
        return (
            HookSpec(
                "codex_hooks.json.template",
                root / ".codex" / "hooks.json",
                template_vars={
                    "WAKE_COMMAND_JSON": json.dumps(
                        _quote_command(
                            hook_runner.as_posix(),
                            "--adapter",
                            "codex-start",
                            "--project-root",
                            root.resolve().as_posix(),
                        )
                    ),
                    "STOP_COMMAND_JSON": json.dumps(
                        _quote_command(
                            hook_runner.as_posix(),
                            "--adapter",
                            "codex-stop",
                            "--project-root",
                            root.resolve().as_posix(),
                        )
                    ),
                },
            ),
        )
    if client == "opencode":
        return (
            HookSpec(
                "opencode_plugin.ts.template",
                root / ".opencode" / "plugins" / "harness-mem.ts",
            ),
        )
    raise ValueError(f"unsupported hook client: {client}")


def _install_hooks(
    client: CommandHost,
    root: Path,
    *,
    force: bool,
    hook_runner: Path | None = None,
) -> list[HookInstallResult]:
    resolved_runner = hook_runner or installer.verified_hook_runner()
    generated_at = datetime.now(timezone.utc)
    if client == "hermes":
        return installer.install_hermes_hook_suite(
            project_root=root,
            force=force,
            harness_mem_version=__version__,
            generated_at=generated_at,
            doc_pointer=installer.DEFAULT_DOC_POINTER,
            hook_runner=resolved_runner,
        )
    if client == "antigravity":
        return installer.install_antigravity_hook_suite(
            project_root=root,
            force=force,
            harness_mem_version=__version__,
            generated_at=generated_at,
            doc_pointer=installer.DEFAULT_DOC_POINTER,
            hook_runner=resolved_runner,
        )
    return installer.install_hook_suite(
        specs=_suite_specs(client, root, resolved_runner),
        project_root=root,
        force=force,
        harness_mem_version=__version__,
        generated_at=generated_at,
        doc_pointer=installer.DEFAULT_DOC_POINTER,
        hook_runner=resolved_runner,
    )


def _hook_stage_result(
    client: CommandHost, results: list[HookInstallResult]
) -> RepairStageResult:
    statuses = {item.status for item in results}
    status: RepairStatus
    if "updated" in statuses:
        status = "updated"
    elif "installed" in statuses:
        status = "installed"
    else:
        status = "unchanged"
    return RepairStageResult(
        host=client,
        stage="hooks",
        status=status,
        artifacts=tuple(str(item.target_path) for item in results),
    )


def _overall_status(results: list[RepairStageResult]) -> OverallStatus:
    statuses = [result.status for result in results]
    failed = statuses.count("failed")
    if failed == len(statuses):
        return "failed"
    if statuses and all(status == "unsupported" for status in statuses):
        return "unsupported"
    if failed or "unsupported" in statuses:
        return "partial_failure"
    return "success"


def repair_integrations(
    *,
    clients: tuple[CommandHost, ...] = COMMAND_HOSTS,
    project_root: Path,
    force: bool = False,
    source_dir: Path | None = None,
    hook_runner_provider: Callable[[], Path] | None = None,
) -> IntegrationRepairReport:
    """Repair hooks and user-level memory commands without dropping failures."""

    root = project_root.resolve()
    results: list[RepairStageResult] = []
    for client in clients:
        try:
            hook_runner = hook_runner_provider() if hook_runner_provider else None
            results.append(
                _hook_stage_result(
                    client,
                    _install_hooks(
                        client,
                        root,
                        force=force,
                        hook_runner=hook_runner,
                    ),
                )
            )
        except NotImplementedError as exc:
            results.append(
                RepairStageResult(
                    host=client,
                    stage="hooks",
                    status="unsupported",
                    error=str(exc),
                )
            )
        except Exception as exc:  # noqa: BLE001 - preserve every stage result
            results.append(
                RepairStageResult(
                    host=client,
                    stage="hooks",
                    status="failed",
                    error=str(exc),
                )
            )

        try:
            command_result = sync_host_commands(
                client=client,
                scope="user",
                source_dir=source_dir,
            )
            results.append(
                RepairStageResult(
                    host=client,
                    stage="commands",
                    status=command_result.status,
                    artifacts=(str(command_result.destination_dir),),
                )
            )
        except NotImplementedError as exc:
            results.append(
                RepairStageResult(
                    host=client,
                    stage="commands",
                    status="unsupported",
                    error=str(exc),
                )
            )
        except Exception as exc:  # noqa: BLE001 - preserve every stage result
            results.append(
                RepairStageResult(
                    host=client,
                    stage="commands",
                    status="failed",
                    error=str(exc),
                )
            )

    status = _overall_status(results)
    return IntegrationRepairReport(
        status=status,
        success=status == "success",
        results=tuple(results),
    )
