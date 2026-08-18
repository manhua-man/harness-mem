"""Merged-config loader for harness-mem runtime configuration.

Both MCP handlers and the host entry consume :func:`load_merged_config`, which
deep-merges ``~/.harness-mem/config.toml`` (user-level) and
``<project_root>/.harness-mem.toml`` (project-level) into a frozen
:class:`MergedConfig`. The project-level file overrides the user-level file at
the leaf-key level; recognized keys absent from both files fall back to their
declared defaults. See design.md "Merged Configuration Loader" + "Data Models".

The user-level config path is resolved through :func:`_user_config_path`, which
reads ``Path.home()`` so tests can isolate the lookup by monkeypatching
``Path.home``.
"""

from __future__ import annotations

import copy
import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from harness_mem.config.errors import (
    ConfigParseError,
    ConfigPathError,
    ConfigValidationError,
)

__all__ = [
    "MergedConfig",
    "PUBLIC_CONFIG_KEY_PATHS",
    "deep_merge",
    "load_merged_config",
]


@dataclass(frozen=True)
class MergedConfig:
    """Result of :func:`load_merged_config`.

    Frozen so neither the MCP handler nor the host entry can mutate the shared
    configuration after it is loaded. Recognized keys land on typed fields;
    everything else is preserved (nested-table shape intact) in ``extras``.
    """

    capture_enabled: bool = True
    capture_private_tags: bool = True
    capture_ignore_clients: tuple[str, ...] = ()
    capture_ignore_session_ids: tuple[str, ...] = ()
    capture_ignore_source_globs: tuple[str, ...] = ()
    transcript_retention_days: int = 0
    distill_auto_enabled: bool = True
    distill_autonomous_enabled: bool = False
    distill_auto_max_jobs_per_wake: int = 2
    distill_auto_target_backlog: int = 2
    distill_auto_recent_first: bool = True
    distill_auto_daily_job_budget: int = 8
    distill_delete_source_after_complete: bool = True
    archive_distill_enabled: bool = False
    archive_distill_batch_size: int = 3
    archive_distill_daily_limit: int = 20
    archive_distill_order: Literal["recent_first", "oldest_first"] = "recent_first"
    archive_distill_project_scope: Literal["detected", "current", "all"] = "current"
    archive_distill_unresolved_project: Literal["defer", "skip", "error"] = "defer"
    archive_distill_warn_tokens: int = 15000
    archive_distill_warn_seconds: int = 40
    archive_distill_require_answer_packet: bool = True
    archive_distill_report_promotions: bool = True
    dream_auto_enabled: bool = True
    dream_auto_trigger: Literal["idle_or_interval", "interval", "idle"] = (
        "idle_or_interval"
    )
    dream_auto_min_interval_hours: int = 24
    dream_auto_idle_seconds: int = 900
    dream_auto_max_runtime_seconds: int = 120
    dream_parse_parse_all: bool = True
    dream_parse_require_evidence: bool = True
    dream_handle_handle_all: bool = True
    # Retained as a read-compatible setting during 0.9.x. Dream no longer
    # interprets it as permission to mutate truth; every proposal re-enters
    # verification and assimilation.
    dream_handle_auto_apply: bool = False
    dream_handle_auto_reject_uncertain: bool = True
    dream_handle_auto_archive_unclassifiable: bool = True
    dream_handle_allow_supersede: bool = True
    dream_handle_allow_merge: bool = True
    dream_handle_allow_mark_stale: bool = True
    dream_handle_allow_delete_truth: bool = False
    dream_handle_preserve_audit: bool = True
    dream_handle_undo_window_days: int = 30
    cost_budget_wake_tokens: int = 2000
    cost_budget_search_tokens: int = 1200
    cost_budget_file_context_tokens: int = 900
    cost_budget_dream_tokens: int = 2000
    cost_budget_distill_tokens: int = 3000
    extras: dict[str, Any] = field(default_factory=dict)

    def to_reflection_config(self) -> dict[str, Any]:
        """Compatibility alias for :meth:`to_runtime_config`."""

        return self.to_runtime_config()

    def to_runtime_config(self) -> dict[str, Any]:
        """Project to the nested-dict shape used by runtime policy readers.

        Rebuilds TOML key-path nesting from a deep copy of ``extras`` and
        overlays recognized runtime keys at their dotted paths. Recognized keys
        therefore take precedence over any same-path value that happened to
        live in ``extras``.
        """
        out: dict[str, Any] = copy.deepcopy(self.extras)
        for key_path, attr, _allowed, _default in _RECOGNIZED_KEYS:
            _set_dotted(out, key_path, getattr(self, attr))
        for key_path, attr, _kind, _default in _TYPED_CONFIG_KEYS:
            _set_dotted(out, key_path, getattr(self, attr))
        return out


# Legacy trigger keys removed from the supported runtime config.
_RECOGNIZED_KEYS: tuple[tuple[str, str, tuple[str, ...], str], ...] = ()
_REMOVED_CONFIG_KEYS: tuple[str, ...] = (
    "autopilot.enabled",
    "triggers.after_agent",
    "triggers.scheduler",
    "distill.mode",
    "worker.mode",
)

_CAPTURE_KEYS: tuple[tuple[str, str, str, Any], ...] = (
    ("capture.enabled", "capture_enabled", "bool", True),
    ("capture.private_tags", "capture_private_tags", "bool", True),
    ("capture.ignore_clients", "capture_ignore_clients", "str_list", ()),
    ("capture.ignore_session_ids", "capture_ignore_session_ids", "str_list", ()),
    ("capture.ignore_source_globs", "capture_ignore_source_globs", "str_list", ()),
    ("transcript.retention_days", "transcript_retention_days", "int:min=0", 0),
)

_DISTILL_KEYS: tuple[tuple[str, str, str, Any], ...] = (
    ("distill.auto.enabled", "distill_auto_enabled", "bool", True),
    (
        "distill.autonomous.enabled",
        "distill_autonomous_enabled",
        "bool",
        False,
    ),
    (
        "distill.auto.max_jobs_per_wake",
        "distill_auto_max_jobs_per_wake",
        "int:min=1:max=3",
        2,
    ),
    (
        "distill.auto.target_backlog",
        "distill_auto_target_backlog",
        "int:min=0",
        2,
    ),
    ("distill.auto.recent_first", "distill_auto_recent_first", "bool", True),
    (
        "distill.auto.daily_job_budget",
        "distill_auto_daily_job_budget",
        "int:min=1",
        8,
    ),
    (
        "distill.delete_source_after_complete",
        "distill_delete_source_after_complete",
        "bool",
        True,
    ),
)

_ARCHIVE_DISTILL_KEYS: tuple[tuple[str, str, str, Any], ...] = (
    ("archive_distill.enabled", "archive_distill_enabled", "bool", False),
    (
        "archive_distill.batch_size",
        "archive_distill_batch_size",
        "int:min=1:max=100",
        3,
    ),
    (
        "archive_distill.daily_limit",
        "archive_distill_daily_limit",
        "int:min=1:max=10000",
        20,
    ),
    (
        "archive_distill.order",
        "archive_distill_order",
        "enum:recent_first,oldest_first",
        "recent_first",
    ),
    (
        "archive_distill.project_scope",
        "archive_distill_project_scope",
        "enum:detected,current,all",
        "current",
    ),
    (
        "archive_distill.unresolved_project",
        "archive_distill_unresolved_project",
        "enum:defer,skip,error",
        "defer",
    ),
    (
        "archive_distill.warn_tokens",
        "archive_distill_warn_tokens",
        "int:min=1",
        15000,
    ),
    (
        "archive_distill.warn_seconds",
        "archive_distill_warn_seconds",
        "int:min=1",
        40,
    ),
    (
        "archive_distill.require_answer_packet",
        "archive_distill_require_answer_packet",
        "bool",
        True,
    ),
    (
        "archive_distill.report_promotions",
        "archive_distill_report_promotions",
        "bool",
        True,
    ),
)

_DREAM_KEYS: tuple[tuple[str, str, str, Any], ...] = (
    ("dream.auto.enabled", "dream_auto_enabled", "bool", True),
    (
        "dream.auto.trigger",
        "dream_auto_trigger",
        "enum:idle_or_interval,interval,idle",
        "idle_or_interval",
    ),
    ("dream.auto.min_interval_hours", "dream_auto_min_interval_hours", "int:min=1", 24),
    ("dream.auto.idle_seconds", "dream_auto_idle_seconds", "int:min=0", 900),
    (
        "dream.auto.max_runtime_seconds",
        "dream_auto_max_runtime_seconds",
        "int:min=1",
        120,
    ),
    ("dream.parse.parse_all", "dream_parse_parse_all", "const:true", True),
    ("dream.parse.require_evidence", "dream_parse_require_evidence", "bool", True),
    ("dream.handle.handle_all", "dream_handle_handle_all", "const:true", True),
    ("dream.handle.auto_apply", "dream_handle_auto_apply", "bool", False),
    (
        "dream.handle.auto_reject_uncertain",
        "dream_handle_auto_reject_uncertain",
        "bool",
        True,
    ),
    (
        "dream.handle.auto_archive_unclassifiable",
        "dream_handle_auto_archive_unclassifiable",
        "bool",
        True,
    ),
    ("dream.handle.allow_supersede", "dream_handle_allow_supersede", "bool", True),
    ("dream.handle.allow_merge", "dream_handle_allow_merge", "bool", True),
    ("dream.handle.allow_mark_stale", "dream_handle_allow_mark_stale", "bool", True),
    (
        "dream.handle.allow_delete_truth",
        "dream_handle_allow_delete_truth",
        "const:false",
        False,
    ),
    ("dream.handle.preserve_audit", "dream_handle_preserve_audit", "const:true", True),
    ("dream.handle.undo_window_days", "dream_handle_undo_window_days", "int:min=1", 30),
)

_COST_BUDGET_KEYS: tuple[tuple[str, str, str, Any], ...] = (
    ("cost_budget.wake_tokens", "cost_budget_wake_tokens", "int:min=1", 2000),
    ("cost_budget.search_tokens", "cost_budget_search_tokens", "int:min=1", 1200),
    (
        "cost_budget.file_context_tokens",
        "cost_budget_file_context_tokens",
        "int:min=1",
        900,
    ),
    ("cost_budget.dream_tokens", "cost_budget_dream_tokens", "int:min=1", 2000),
    ("cost_budget.distill_tokens", "cost_budget_distill_tokens", "int:min=1", 3000),
)

_TYPED_CONFIG_KEYS: tuple[tuple[str, str, str, Any], ...] = (
    *_CAPTURE_KEYS,
    *_DISTILL_KEYS,
    *_ARCHIVE_DISTILL_KEYS,
    *_DREAM_KEYS,
    *_COST_BUDGET_KEYS,
)

# The public policy surface stays intentionally small. The remaining typed
# keys are still read for 0.9.x compatibility, but they are internal runtime
# tuning rather than user-facing product modes.
PUBLIC_CONFIG_KEY_PATHS: tuple[str, ...] = (
    "capture.enabled",
    "capture.private_tags",
    "capture.ignore_clients",
    "capture.ignore_session_ids",
    "capture.ignore_source_globs",
    "transcript.retention_days",
    "distill.auto.enabled",
    "distill.autonomous.enabled",
    "distill.delete_source_after_complete",
    "archive_distill.enabled",
    "archive_distill.batch_size",
    "archive_distill.daily_limit",
    "archive_distill.order",
    "archive_distill.project_scope",
    "archive_distill.unresolved_project",
    "archive_distill.warn_tokens",
    "archive_distill.warn_seconds",
    "archive_distill.require_answer_packet",
    "archive_distill.report_promotions",
    "dream.auto.enabled",
)
_PUBLIC_CONFIG_KEY_SET = frozenset(PUBLIC_CONFIG_KEY_PATHS)
_PUBLIC_TYPED_CONFIG_KEYS = tuple(
    item for item in _TYPED_CONFIG_KEYS if item[0] in _PUBLIC_CONFIG_KEY_SET
)
_INTERNAL_TYPED_CONFIG_KEYS = tuple(
    item for item in _TYPED_CONFIG_KEYS if item[0] not in _PUBLIC_CONFIG_KEY_SET
)
INTERNAL_CONFIG_KEY_PATHS = frozenset(
    key_path for key_path, *_rest in _INTERNAL_TYPED_CONFIG_KEYS
)


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` onto ``base``; ``overlay`` wins at leaves.

    Tables present in only one of the two inputs are preserved unchanged. A
    leaf value (anything that is not a dict) in ``overlay`` replaces the value
    at the same key path in ``base``.
    """
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _get_dotted(d: dict[str, Any], dotted: str) -> tuple[bool, Any]:
    """Return ``(found, value)`` for a dotted key path in a nested dict."""
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return (False, None)
        cur = cur[part]
    return (True, cur)


def _set_dotted(d: dict[str, Any], dotted: str, value: Any) -> None:
    """Set a dotted key path in a nested dict, creating intermediate tables."""
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _remove_dotted(d: dict[str, Any], dotted: str) -> None:
    """Remove a dotted key path from a nested dict; prune emptied parents.

    Recognized keys are stripped from the copy of the merged dict that becomes
    ``extras`` so that ``extras`` carries only unrecognized keys. Sibling
    unrecognized keys under the same table survive (e.g. removing
    ``dream.auto.enabled`` leaves sibling dream keys in place).
    """
    parts = dotted.split(".")
    chain: list[tuple[dict[str, Any], str]] = []
    cur = d
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            return  # path does not exist as nested tables; nothing to remove
        chain.append((cur, part))
        cur = nxt
    last = parts[-1]
    if last in cur:
        del cur[last]
    # Prune parents that became empty as a result of the removal.
    for parent, key in reversed(chain):
        child = parent.get(key)
        if isinstance(child, dict) and not child:
            del parent[key]


def _source_for_key(
    key_path: str,
    *,
    project_dict: dict[str, Any],
    user_dict: dict[str, Any],
    project_path: Path,
    user_path: Path,
) -> str:
    in_project, _ = _get_dotted(project_dict, key_path)
    return str(project_path if in_project else user_path)


def _coerce_bool(value: Any, *, key_path: str, source_path: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigValidationError(key_path=key_path, value=value, source_path=source_path)


def _coerce_int(
    value: Any,
    *,
    key_path: str,
    source_path: str,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise ConfigValidationError(
            key_path=key_path, value=value, source_path=source_path
        )
    return value


def _coerce_typed_value(
    *,
    key_path: str,
    kind: str,
    value: Any,
    source_path: str,
) -> Any:
    if kind == "bool":
        return _coerce_bool(value, key_path=key_path, source_path=source_path)
    if kind == "str_list":
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise ConfigValidationError(
                key_path=key_path, value=value, source_path=source_path
            )
        return tuple(dict.fromkeys(item.strip() for item in value if item.strip()))
    if kind == "const:true":
        coerced = _coerce_bool(value, key_path=key_path, source_path=source_path)
        if coerced is not True:
            raise ConfigValidationError(
                key_path=key_path, value=value, source_path=source_path
            )
        return coerced
    if kind == "const:false":
        coerced = _coerce_bool(value, key_path=key_path, source_path=source_path)
        if coerced is not False:
            raise ConfigValidationError(
                key_path=key_path, value=value, source_path=source_path
            )
        return coerced
    if kind.startswith("int:min="):
        bounds = kind.removeprefix("int:min=").split(":max=", maxsplit=1)
        minimum = int(bounds[0])
        maximum = int(bounds[1]) if len(bounds) == 2 else None
        return _coerce_int(
            value,
            key_path=key_path,
            source_path=source_path,
            minimum=minimum,
            maximum=maximum,
        )
    if kind.startswith("enum:"):
        allowed = tuple(kind.removeprefix("enum:").split(","))
        if value not in allowed:
            raise ConfigValidationError(
                key_path=key_path, value=value, source_path=source_path
            )
        return value
    raise ConfigValidationError(key_path=key_path, value=value, source_path=source_path)


def _coerce_dream_value(
    *,
    key_path: str,
    kind: str,
    value: Any,
    source_path: str,
) -> Any:
    return _coerce_typed_value(
        key_path=key_path,
        kind=kind,
        value=value,
        source_path=source_path,
    )


def _coerce_key_group(
    *,
    merged: dict[str, Any],
    keys: tuple[tuple[str, str, str, Any], ...],
    project_dict: dict[str, Any],
    user_dict: dict[str, Any],
    project_path: Path,
    user_path: Path,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key_path, attr, kind, default in keys:
        found, value = _get_dotted(merged, key_path)
        if not found:
            values[attr] = default
            continue
        source_path = _source_for_key(
            key_path,
            project_dict=project_dict,
            user_dict=user_dict,
            project_path=project_path,
            user_path=user_path,
        )
        values[attr] = _coerce_typed_value(
            key_path=key_path,
            kind=kind,
            value=value,
            source_path=source_path,
        )
    return values


def _user_config_path() -> Path:
    """Resolve the user-level config path (``~/.harness-mem/config.toml``).

    Reads ``Path.home()`` so tests can redirect the lookup by monkeypatching
    ``Path.home`` to a temporary directory.
    """
    return Path.home() / ".harness-mem" / "config.toml"


def _legacy_user_config_path() -> Path:
    return Path.home() / ".harness-mem" / "config.json"


def _load_toml_file(path: Path) -> dict[str, Any]:
    """Parse a TOML file, treating a missing file as an empty table.

    Raises:
        ConfigParseError: the file exists but is not valid TOML.
    """
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigParseError(source_path=str(path), cause=exc) from exc


def _load_json_file(path: Path) -> dict[str, Any]:
    """Parse a legacy JSON config as a compatibility base layer."""

    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigParseError(source_path=str(path), cause=exc) from exc
    if not isinstance(payload, dict):
        raise ConfigParseError(
            source_path=str(path),
            cause=TypeError("config root must be an object"),
        )
    return payload


def _load_user_config_files() -> tuple[Path, dict[str, Any]]:
    """Return one merged user config with TOML overriding legacy JSON."""

    toml_path = _user_config_path()
    legacy_path = _legacy_user_config_path()
    legacy = _load_json_file(legacy_path)
    current = _load_toml_file(toml_path)
    effective_path = toml_path if toml_path.is_file() else legacy_path
    return effective_path, deep_merge(legacy, current)


def load_merged_config(project_root: str | os.PathLike[str]) -> MergedConfig:
    """Deep-merge the user-level and project-level config into a MergedConfig.

    Args:
        project_root: Absolute path to an existing project directory. Used both
            to locate ``<project_root>/.harness-mem.toml`` and as the
            attribution anchor for project-level values.

    Raises:
        ConfigPathError: ``project_root`` is not absolute or is not an existing
            directory.
        ConfigParseError: a source file is invalid TOML/JSON.
        ConfigValidationError: a recognized key holds a value outside its
            declared allowed set.
    """
    # ---- 1. project_root validation (Req 3.1, 3.2) ----------------------
    if not os.path.isabs(project_root) or not os.path.isdir(project_root):
        raise ConfigPathError(str(project_root))

    # ---- 2. read source files (Req 3.3, 3.4, 3.5, 3.8) ------------------
    user_path, user_dict = _load_user_config_files()
    project_path = Path(project_root) / ".harness-mem.toml"
    project_dict = _load_toml_file(project_path)

    # Model-use authorization is intentionally project-scoped. Ignore legacy
    # user-level values so installing hooks in another project cannot inherit
    # background provider authorization by accident.
    _remove_dotted(user_dict, "distill.autonomous.enabled")

    # ---- 3. deep-merge (project overrides user) (Req 3.3) ---------------
    merged = deep_merge(user_dict, project_dict)

    # ---- 4 + 5. validate recognized keys with source attribution --------
    # For each recognized key, the merged value came from the project file if
    # the key is present there, else from the user file. That attribution is
    # what ConfigValidationError reports as ``source_path`` (Req 3.7).
    for key_path, _attr, allowed, _default in _RECOGNIZED_KEYS:
        found, value = _get_dotted(merged, key_path)
        if not found:
            continue
        if value not in allowed:
            in_project, _ = _get_dotted(project_dict, key_path)
            source_path = str(project_path if in_project else user_path)
            raise ConfigValidationError(
                key_path=key_path, value=value, source_path=source_path
            )

    typed_values = _coerce_key_group(
        merged=merged,
        keys=_TYPED_CONFIG_KEYS,
        project_dict=project_dict,
        user_dict=user_dict,
        project_path=project_path,
        user_path=user_path,
    )
    # ---- 6. default-fill + extras collection (Req 3.6) ------------------
    extras = copy.deepcopy(merged)
    for key_path, _attr, _allowed, _default in _RECOGNIZED_KEYS:
        _remove_dotted(extras, key_path)
    for key_path, _attr, _kind, _default in _TYPED_CONFIG_KEYS:
        _remove_dotted(extras, key_path)
    for key_path in _REMOVED_CONFIG_KEYS:
        _remove_dotted(extras, key_path)

    # ---- 7. construct (Req 3.6, 3.9) ------------------------------------
    return MergedConfig(
        **typed_values,
        extras=extras,
    )
