"""Configuration error hierarchy for the v2.4.1 merged-config loader.

All failures raised by :func:`harness_mem.config.merge.load_merged_config`
subclass :class:`ConfigError`, so a host entry or MCP handler can catch the
single base class and degrade gracefully. Each subclass carries the
failure-attribution attributes a diagnostic needs (offending path / key /
value / cause).
"""

from __future__ import annotations


class ConfigError(Exception):
    """Base for all load_merged_config failures. Hosts catch this one class."""


class ConfigPathError(ConfigError):
    """project_root is not absolute or does not exist."""

    def __init__(self, project_root: str) -> None:
        self.project_root = project_root
        super().__init__(
            f"invalid project_root: {project_root!r} "
            "(must be an absolute path to an existing directory)"
        )


class ConfigParseError(ConfigError):
    """A source TOML file failed to parse."""

    def __init__(self, source_path: str, cause: Exception | None = None) -> None:
        self.source_path = source_path
        self.cause = cause
        msg = f"failed to parse config file: {source_path}"
        if cause is not None:
            msg += f" ({cause})"
        super().__init__(msg)


class ConfigValidationError(ConfigError):
    """A recognized key holds a value outside its allowed set."""

    def __init__(self, key_path: str, value: object, source_path: str) -> None:
        self.key_path = key_path
        self.value = value
        self.source_path = source_path
        super().__init__(
            f"invalid value for {key_path}: {value!r} (in {source_path})"
        )


__all__ = [
    "ConfigError",
    "ConfigPathError",
    "ConfigParseError",
    "ConfigValidationError",
]
