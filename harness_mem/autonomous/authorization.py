"""Background memory authorization (distill.autonomous.enabled + host CLI)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _runtime_view(config: Any) -> Mapping[str, Any]:
    if config is None:
        return {}
    if hasattr(config, "to_runtime_config"):
        view = config.to_runtime_config()
        return view if isinstance(view, Mapping) else {}
    if isinstance(config, Mapping):
        return config
    enabled = getattr(config, "distill_autonomous_enabled", None)
    extras = getattr(config, "extras", None)
    if isinstance(extras, Mapping):
        return {
            **extras,
            "distill": {"autonomous": {"enabled": enabled}},
        }
    if enabled is None:
        return {}
    return {"distill": {"autonomous": {"enabled": enabled}}}


def _distill_autonomous_enabled(view: Mapping[str, Any]) -> bool:
    distill = view.get("distill")
    autonomous = distill.get("autonomous") if isinstance(distill, Mapping) else None
    if not isinstance(autonomous, Mapping):
        return False
    return _coerce_bool(autonomous.get("enabled"), default=False)


def background_on(config: Any) -> bool:
    """True when the project turned background work on."""

    view = _runtime_view(config)
    return _distill_autonomous_enabled(view)


@dataclass(frozen=True)
class BackgroundStatus:
    ready: bool
    on: bool
    reason: str
    selected_cli: str | None = None


_REASON_MESSAGES = {
    "ok": "Background is on and the selected CLI is available.",
    "disabled": "Background is off (distill.autonomous.enabled=false).",
    "host_not_detected": "Background is on, but the current Agent could not be identified.",
    "unsupported_cli": "Background is on, but the selected CLI is not supported.",
    "cli_not_found": "Background is on, but the selected CLI executable was not found.",
}


def background_reason_message(reason: str) -> str:
    return _REASON_MESSAGES.get(reason, reason)


def background_status(config: Any, *, client: str | None = None) -> BackgroundStatus:
    view = _runtime_view(config)
    on = background_on(config)
    selected_cli: str | None = None
    if not _distill_autonomous_enabled(view):
        reason = "disabled"
    else:
        from harness_mem.autonomous.executors.registry import inspect_semantic_executor
        from harness_mem.commands.support import detect_runtime_client, normalize_client_name
        from harness_mem.config.merge import MergedConfig

        current_client = normalize_client_name(client) if client else None
        if current_client in {None, "auto", "agent"}:
            current_client = detect_runtime_client()
        distill = view.get("distill")
        autonomous = distill.get("autonomous") if isinstance(distill, Mapping) else {}
        configured_cli = str(
            (autonomous.get("cli") or "current")
            if isinstance(autonomous, Mapping)
            else "current"
        )
        if configured_cli == "current" and current_client is None:
            reason = "host_not_detected"
        elif isinstance(config, MergedConfig):
            selected_cli, reason = inspect_semantic_executor(
                config,
                current_client or "unknown",
            )
        else:
            from harness_mem.autonomous.executors.constants import AGENT_HOST_CLIENTS
            from harness_mem.autonomous.executors.host_cli import _resolve_executable

            selected_cli = (
                configured_cli if configured_cli != "current" else current_client
            )
            selected_cli = normalize_client_name(selected_cli)
            if selected_cli not in AGENT_HOST_CLIENTS:
                reason = "unsupported_cli"
            elif not _resolve_executable(selected_cli):
                reason = "cli_not_found"
            else:
                reason = "ok"
    return BackgroundStatus(
        ready=reason == "ok",
        on=on,
        reason=reason,
        selected_cli=selected_cli if on else None,
    )
