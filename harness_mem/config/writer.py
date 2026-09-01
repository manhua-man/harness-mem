"""Single-key TOML writer for the ``config set`` maintenance command.

``config set`` edits a single project or user config key without hand-editing
TOML. The write model is a structured edit: read the existing file into a
``dict``, mutate exactly one leaf under a dotted key path, and write the whole
table back via :func:`tomli_w.dumps`. Comments and key ordering are NOT
preserved.

Recognized-key validation reuses the merge module's typed key registry so the
writer and loader cannot disagree about allowed values. Only public policy
keys are writable; retained tuning keys are read-only compatibility input.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

import tomli_w

from harness_mem.config.errors import ConfigParseError, ConfigValidationError
from harness_mem.config.merge import (
    INTERNAL_CONFIG_KEY_PATHS,
    PUBLIC_CONFIG_KEY_PATHS,
    _RECOGNIZED_KEYS,
    _REMOVED_CONFIG_KEYS,
    _TYPED_CONFIG_KEYS,
    _remove_dotted,
    _set_dotted,
)

__all__ = ["set_value"]


def _target_path(
    scope: Literal["user", "project"], project_root: str | os.PathLike[str]
) -> Path:
    """Resolve the Config_File path for the requested scope (Req 2.3, 2.4).

    User scope writes ``~/.harness-mem/config.toml`` (resolved through
    ``Path.home()`` so tests can isolate it by monkeypatching ``Path.home``);
    project scope writes ``<project_root>/.harness-mem.toml``.
    """
    if scope == "user":
        return Path.home() / ".harness-mem" / "config.toml"
    return Path(project_root) / ".harness-mem.toml"


def _read_existing(path: Path) -> dict[str, Any]:
    """Parse an existing Config_File, treating a missing file as ``{}``.

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


def _parse_bool(value: str, *, key_path: str, target: Path) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ConfigValidationError(
        key_path=key_path, value=value, source_path=str(target)
    )


def _parse_int(
    value: str,
    *,
    key_path: str,
    target: Path,
    minimum: int,
    maximum: int | None = None,
) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigValidationError(
            key_path=key_path, value=value, source_path=str(target)
        ) from exc
    if parsed < minimum or (maximum is not None and parsed > maximum):
        raise ConfigValidationError(
            key_path=key_path, value=value, source_path=str(target)
        )
    return parsed


def _parse_str_list(value: str, *, key_path: str, target: Path) -> list[str]:
    """Parse one TOML array literal for a typed string-list config key."""

    try:
        parsed = tomllib.loads(f"value = {value}")["value"]
    except (KeyError, tomllib.TOMLDecodeError) as exc:
        raise ConfigValidationError(
            key_path=key_path, value=value, source_path=str(target)
        ) from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise ConfigValidationError(
            key_path=key_path, value=value, source_path=str(target)
        )
    return list(dict.fromkeys(item.strip() for item in parsed if item.strip()))


def _parse_bounded_string(
    value: str,
    *,
    key_path: str,
    target: Path,
    minimum: int,
    maximum: int | None = None,
) -> str:
    parsed = value.strip()
    if len(parsed) < minimum or (maximum is not None and len(parsed) > maximum):
        raise ConfigValidationError(
            key_path=key_path, value=value, source_path=str(target)
        )
    return parsed


def _validate(key_path: str, value: str, target: Path) -> Any:
    """Validate a public policy value and reject internal tuning keys."""
    if key_path in _REMOVED_CONFIG_KEYS or key_path.startswith("triggers."):
        raise ConfigValidationError(
            key_path=key_path, value=value, source_path=str(target)
        )
    if key_path in INTERNAL_CONFIG_KEY_PATHS:
        raise ConfigValidationError(
            key_path=key_path,
            value="internal compatibility key",
            source_path=str(target),
        )
    if key_path not in PUBLIC_CONFIG_KEY_PATHS:
        raise ConfigValidationError(
            key_path=key_path,
            value="unknown public policy key",
            source_path=str(target),
        )
    for recognized_path, _attr, allowed, _default in _RECOGNIZED_KEYS:
        if recognized_path == key_path and value not in allowed:
            raise ConfigValidationError(
                key_path=key_path, value=value, source_path=str(target)
            )
        if recognized_path == key_path:
            return value
    for recognized_path, _attr, kind, _default in _TYPED_CONFIG_KEYS:
        if recognized_path != key_path:
            continue
        if kind == "bool":
            return _parse_bool(value, key_path=key_path, target=target)
        if kind == "const:true":
            parsed = _parse_bool(value, key_path=key_path, target=target)
            if parsed is not True:
                raise ConfigValidationError(
                    key_path=key_path, value=value, source_path=str(target)
                )
            return parsed
        if kind == "const:false":
            parsed = _parse_bool(value, key_path=key_path, target=target)
            if parsed is not False:
                raise ConfigValidationError(
                    key_path=key_path, value=value, source_path=str(target)
                )
            return parsed
        if kind.startswith("int:min="):
            bounds = kind.removeprefix("int:min=").split(":max=", maxsplit=1)
            return _parse_int(
                value,
                key_path=key_path,
                target=target,
                minimum=int(bounds[0]),
                maximum=int(bounds[1]) if len(bounds) == 2 else None,
            )
        if kind.startswith("str:min="):
            bounds = kind.removeprefix("str:min=").split(":max=", maxsplit=1)
            return _parse_bounded_string(
                value,
                key_path=key_path,
                target=target,
                minimum=int(bounds[0]),
                maximum=int(bounds[1]) if len(bounds) == 2 else None,
            )
        if kind.startswith("enum:"):
            allowed = tuple(kind.removeprefix("enum:").split(","))
            if value not in allowed:
                raise ConfigValidationError(
                    key_path=key_path, value=value, source_path=str(target)
                )
            return value
        if kind == "str_list":
            return _parse_str_list(value, key_path=key_path, target=target)
    return value


def set_value(
    *,
    scope: Literal["user", "project"],
    project_root: str | os.PathLike[str],
    key_path: str,
    value: str,
) -> Path:
    """Write a single key/value to the chosen Config_File.

    Reads the existing TOML (empty dict when the file is absent), updates the
    leaf key under the dotted ``key_path``, and writes the entire dict back via
    :func:`tomli_w.dumps`. The parent directory is created on demand.

    Args:
        scope: ``"user"`` writes ``~/.harness-mem/config.toml``; ``"project"``
            writes ``<project_root>/.harness-mem.toml``.
        project_root: Project directory used to locate the project-level file.
        key_path: Dotted key path to set (for example ``dream.auto.enabled``).
        value: Literal string value to write.

    Returns:
        The absolute :class:`~pathlib.Path` of the file written.

    Raises:
        ConfigParseError: the target file exists but is not valid TOML.
        ConfigValidationError: ``key_path`` is a Recognized_Key and ``value`` is
            outside its declared allowed-value set.
        OSError: the file cannot be written (caller surfaces as exit 1).
    """
    target = _target_path(scope, project_root)
    if key_path == "semantic.execution.restricted":
        if scope != "project":
            raise ConfigValidationError(
                key_path=key_path,
                value="project scope required",
                source_path=str(target),
            )
        data = _read_existing(target)
        restricted = _parse_bool(value, key_path=key_path, target=target)
        if restricted is False:
            _set_dotted(data, "distill.autonomous.enabled", False)
        _remove_dotted(data, "semantic.execution.restricted")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(tomli_w.dumps(data), encoding="utf-8")
        return target.resolve()
    if key_path in {
        "distill.autonomous.enabled",
        "distill.autonomous.cli",
    } and scope != "project":
        raise ConfigValidationError(
            key_path=key_path,
            value="project scope required",
            source_path=str(target),
        )
    data = _read_existing(target)
    parsed_value = _validate(key_path, value, target)
    _set_dotted(data, key_path, parsed_value)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(tomli_w.dumps(data), encoding="utf-8")
    return target.resolve()
