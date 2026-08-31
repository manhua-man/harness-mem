"""Handlers for the v2.4.3 ``harness-mem config`` maintenance subcommands.

These four handlers are the CLI surface for managing the user-level and
project-level Config_File set (Req 1-4). They are deliberately thin: every read
routes through the v2.4.1 :func:`harness_mem.config.merge.load_merged_config`
loader and every write routes through :func:`harness_mem.config.writer.set_value`.
The CLI layer never re-implements deep-merge, default-fill, or validation logic
(Req 1.7, 4.7) — those live exactly once in the config package.

Output contract (see design.md "Error Handling" table): resolved values and
success confirmations go to stdout via :func:`print`; diagnostics go to stderr.
Exit codes are returned as ``int`` for the CLI dispatcher to propagate.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from harness_mem.config.errors import (
    ConfigParseError,
    ConfigValidationError,
)
from harness_mem.config.merge import (
    INTERNAL_CONFIG_KEY_PATHS,
    PUBLIC_CONFIG_KEY_PATHS,
    _PUBLIC_TYPED_CONFIG_KEYS,
    _RECOGNIZED_KEYS,
    _TYPED_CONFIG_KEYS,
    _get_dotted,
    _load_user_config_files,
    _user_config_path,
    load_merged_config,
)
from harness_mem.config.writer import set_value

__all__ = [
    "cmd_config_get",
    "cmd_config_set",
    "cmd_config_list",
    "cmd_config_validate",
]


def _resolve_project_root(project_root: str | None) -> str:
    """Resolve ``--project-root`` to an absolute path (default: cwd).

    ``load_merged_config`` requires an absolute path, so a relative
    ``--project-root`` is anchored against the current working directory.
    """
    if project_root is None:
        return os.getcwd()
    return os.path.abspath(project_root)


def _project_config_path(project_root: str) -> Path:
    """Project-level Config_File path: ``<project_root>/.harness-mem.toml``."""
    return Path(project_root) / ".harness-mem.toml"


def _read_raw(path: Path) -> dict[str, Any]:
    """Parse a Config_File into a raw dict; a missing file is an empty table."""
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _allowed_for(key: str) -> tuple[str, ...] | None:
    """Return the allowed-value tuple for a Recognized_Key, else ``None``."""
    for recognized_path, _attr, allowed, _default in _RECOGNIZED_KEYS:
        if recognized_path == key:
            return allowed
    for recognized_path, _attr, kind, _default in _TYPED_CONFIG_KEYS:
        if recognized_path != key:
            continue
        if kind == "bool":
            return ("true", "false")
        if kind == "const:true":
            return ("true",)
        if kind == "const:false":
            return ("false",)
        if kind.startswith("enum:"):
            return tuple(kind.removeprefix("enum:").split(","))
        if kind.startswith("int:min="):
            bounds = kind.removeprefix("int:min=").split(":max=", maxsplit=1)
            description = f"integer >= {bounds[0]}"
            if len(bounds) == 2:
                description += f" and <= {bounds[1]}"
            return (description,)
        if kind.startswith("str:min="):
            bounds = kind.removeprefix("str:min=").split(":max=", maxsplit=1)
            description = f"non-empty string of at least {bounds[0]} characters"
            if len(bounds) == 2:
                description += f" and at most {bounds[1]} characters"
            return (description,)
        if kind == "str_list":
            return ('TOML string list, e.g. ["codex", "cursor"]',)
    return None


def _format_config_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _flatten(table: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    """Flatten a nested table into ``(dotted_key, leaf_value)`` pairs."""
    out: list[tuple[str, Any]] = []
    for key, value in table.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.extend(_flatten(value, dotted))
        else:
            out.append((dotted, value))
    return out


def _source_label(
    key: str, project_dict: dict[str, Any], user_dict: dict[str, Any]
) -> str:
    """Attribute a dotted key to ``project``, ``user``, or ``default``.

    Project-level values override user-level values, so a key present in the
    project file is labeled ``project`` regardless of the user file.
    """
    if _get_dotted(project_dict, key)[0]:
        return "project"
    if key == "distill.autonomous.enabled":
        return "default"
    if _get_dotted(user_dict, key)[0]:
        return "user"
    return "default"


def cmd_config_get(key: str, project_root: str | None) -> int:
    """Read a single value from the merged config (Req 1).

    Resolves the dotted ``key`` against the merged config (recognized keys plus
    extras, with recognized-key defaults filled in). Prints the resolved value
    to stdout and exits 0 when found; otherwise emits a diagnostic to stderr and
    exits 1 with no stdout output (Req 1.2, 1.3, 1.4).
    """
    resolved_root = _resolve_project_root(project_root)
    if key not in PUBLIC_CONFIG_KEY_PATHS:
        print(f"key not found: {key}", file=sys.stderr)
        return 1
    merged = load_merged_config(resolved_root)
    found, value = _get_dotted(merged.to_reflection_config(), key)
    if not found:
        print(f"key not found: {key}", file=sys.stderr)
        return 1
    print(_format_config_value(value))
    return 0


def cmd_config_set(
    key: str,
    value: str,
    scope: str,
    project_root: str | None,
    *,
    confirm: bool = False,
) -> int:
    """Write a single value to the chosen Config_File (Req 2).

    Delegates to :func:`harness_mem.config.writer.set_value`. On a rejected
    Recognized_Key value, names the offending key/value and the allowed set on
    stderr; on a filesystem error, names the target path and OS error on stderr
    (see design.md "Error Handling" table).
    """
    resolved_root = _resolve_project_root(project_root)
    if key in {"distill.autonomous.enabled"} and scope != "project":
        print(
            f"invalid scope: {key} may only be set at project scope",
            file=sys.stderr,
        )
        return 1
    if key in INTERNAL_CONFIG_KEY_PATHS:
        print(
            f"invalid value: {key} is an internal compatibility key and is not "
            "part of the public configuration surface",
            file=sys.stderr,
        )
        return 1
    confirmed_enable_keys = {
        "distill.autonomous.enabled": (
            "background model use may send compact transcript evidence to the "
            "configured provider and consume model quota"
        ),
        "distill.delete_source_after_complete": (
            "future completed session sources may be deleted automatically"
        ),
    }
    if key in confirmed_enable_keys and value.strip().lower() in {
        "true",
        "1",
        "yes",
        "on",
    }:
        target = (
            _user_config_path()
            if scope == "user"
            else _project_config_path(resolved_root)
        )
        try:
            found, current = _get_dotted(_read_raw(target), key)
        except tomllib.TOMLDecodeError as exc:
            print(f"parse error: {target}: {exc}", file=sys.stderr)
            return 1
        if (not found or current is not True) and not confirm:
            print(
                f"confirmation required: enabling {key} authorizes "
                f"{confirmed_enable_keys[key]}; rerun with --confirm",
                file=sys.stderr,
            )
            return 1
    try:
        written = set_value(
            scope=scope,  # type: ignore[arg-type]
            project_root=resolved_root,
            key_path=key,
            value=value,
        )
    except ConfigParseError as exc:
        print(f"parse error: {exc.source_path}: {exc.cause}", file=sys.stderr)
        return 1
    except ConfigValidationError:
        allowed = _allowed_for(key) or ()
        allowed_repr = "{" + ", ".join(allowed) + "}"
        print(
            f"invalid value: {key} = {value}; allowed: {allowed_repr}",
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        if scope == "user":
            target = _user_config_path()
        else:
            target = _project_config_path(resolved_root)
        print(f"write failed: {target}: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {written}: {key} = {value}")
    return 0


def cmd_config_list(project_root: str | None, *, detail: str | None = None) -> int:
    """Print the public policy keys with merged source labels.

    Each line is ``<key> = <value>  (<source>)`` where source is one of
    ``default``, ``user``, or ``project``. When neither Config_File exists, a
    header note is printed before the lines. Always exits 0 in non-error cases.
    """
    resolved_root = _resolve_project_root(project_root)
    merged = load_merged_config(resolved_root)

    user_path, user_dict = _load_user_config_files()
    project_path = _project_config_path(resolved_root)
    project_dict = _read_raw(project_path)

    if not user_path.is_file() and not project_path.is_file():
        print("no Config_File found, showing defaults")

    reflection = merged.to_reflection_config()
    for key_path, _attr, _allowed, _default in _RECOGNIZED_KEYS:
        _, value = _get_dotted(reflection, key_path)
        source = _source_label(key_path, project_dict, user_dict)
        print(f"{key_path} = {_format_config_value(value)}  ({source})")

    for key_path, _attr, _kind, _default in _PUBLIC_TYPED_CONFIG_KEYS:
        _, value = _get_dotted(reflection, key_path)
        source = _source_label(key_path, project_dict, user_dict)
        print(f"{key_path} = {_format_config_value(value)}  ({source})")

    if detail == "runtime":
        print("runtime tuning (read-only):")
        public_paths = {item[0] for item in _PUBLIC_TYPED_CONFIG_KEYS}
        for key_path, _attr, _kind, _default in _TYPED_CONFIG_KEYS:
            if key_path in public_paths:
                continue
            _, value = _get_dotted(reflection, key_path)
            source = _source_label(key_path, project_dict, user_dict)
            print(f"{key_path} = {_format_config_value(value)}  ({source})")

    return 0


def cmd_config_validate(project_root: str | None) -> int:
    """Run the shared ``load_merged_config`` validation pipeline.

    Shares its loader with the host entry and doctor surface so validation
    outcomes never disagree (Req 4.7). On success prints a one-line summary; on
    parse or schema failure emits a diagnostic to stderr and exits 1 with no
    stdout success output (Req 4.2, 4.3, 4.4).
    """
    resolved_root = _resolve_project_root(project_root)
    try:
        load_merged_config(resolved_root)
    except ConfigParseError as exc:
        print(
            f"parse error: {exc.source_path}: {exc.cause}",
            file=sys.stderr,
        )
        return 1
    except ConfigValidationError as exc:
        print(
            f"invalid value: {exc.key_path} = {exc.value} at {exc.source_path}",
            file=sys.stderr,
        )
        return 1
    print(f"config valid: {resolved_root}")
    return 0
