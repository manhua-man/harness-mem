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
    restricted = getattr(config, "semantic_execution_restricted", None)
    mode = getattr(config, "semantic_execution_mode", None)
    extras = getattr(config, "extras", None)
    if isinstance(extras, Mapping):
        semantic = extras.get("semantic")
        if isinstance(semantic, Mapping):
            return {
                "distill": {"autonomous": {"enabled": enabled}},
                "semantic": semantic,
            }
    if enabled is None and restricted is None and mode is None:
        return {}
    execution: dict[str, Any] = {}
    if restricted is not None:
        execution["restricted"] = restricted
    if mode is not None:
        execution["mode"] = mode
    return {
        "distill": {"autonomous": {"enabled": enabled}},
        "semantic": {"execution": execution},
    }


def _distill_autonomous_enabled(view: Mapping[str, Any]) -> bool:
    distill = view.get("distill")
    autonomous = distill.get("autonomous") if isinstance(distill, Mapping) else None
    if not isinstance(autonomous, Mapping):
        return False
    return _coerce_bool(autonomous.get("enabled"), default=False)


def _semantic_execution(view: Mapping[str, Any]) -> Mapping[str, Any] | None:
    semantic = view.get("semantic")
    if not isinstance(semantic, Mapping):
        return None
    execution = semantic.get("execution")
    return execution if isinstance(execution, Mapping) else None


def _legacy_restricted_off(view: Mapping[str, Any]) -> bool:
    execution = _semantic_execution(view)
    if execution is None:
        return False
    return execution.get("restricted") is False


def background_on(config: Any) -> bool:
    """True when the project turned background work on (enabled, not legacy-off)."""

    view = _runtime_view(config)
    if not _distill_autonomous_enabled(view):
        return False
    if _legacy_restricted_off(view):
        return False
    return True


def background_ready(config: Any) -> bool:
    """True when background host CLI work may run."""

    return background_on(config)


@dataclass(frozen=True)
class BackgroundStatus:
    ready: bool
    on: bool
    legacy_off: bool
    reason: str


_REASON_MESSAGES = {
    "ok": "Background ready (host CLI for current client).",
    "disabled": "Background is off (distill.autonomous.enabled=false).",
    "legacy_restricted_off": "Background is off (legacy semantic.execution.restricted=false).",
}


def background_reason_message(reason: str) -> str:
    return _REASON_MESSAGES.get(reason, reason)


def background_status(config: Any) -> BackgroundStatus:
    view = _runtime_view(config)
    legacy_off = _legacy_restricted_off(view)
    on = background_on(config)
    if not _distill_autonomous_enabled(view):
        reason = "disabled"
    elif legacy_off:
        reason = "legacy_restricted_off"
    else:
        reason = "ok"
    return BackgroundStatus(
        ready=reason == "ok",
        on=on,
        legacy_off=legacy_off,
        reason=reason,
    )


# Legacy names (keep for one release; prefer background_* in new code).
autonomous_semantic_effective_enabled = background_on
autonomous_semantically_authorized = background_ready
AutonomousAuthorizationStatus = BackgroundStatus
inspect_autonomous_authorization = background_status
