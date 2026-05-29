"""Tests for the v2.4.1 config error hierarchy (Task 1, Req 3 error path)."""

from __future__ import annotations

from harness_mem.config import (
    ConfigError,
    ConfigParseError,
    ConfigPathError,
    ConfigValidationError,
)


def test_config_path_error_carries_project_root() -> None:
    exc = ConfigPathError("relative/path")
    assert exc.project_root == "relative/path"
    assert "relative/path" in str(exc)
    assert isinstance(exc, ConfigError)


def test_config_parse_error_with_cause() -> None:
    cause = ValueError("bad toml")
    exc = ConfigParseError("/abs/path.toml", cause=cause)
    assert exc.source_path == "/abs/path.toml"
    assert exc.cause is cause
    assert "/abs/path.toml" in str(exc)
    assert "bad toml" in str(exc)
    assert isinstance(exc, ConfigError)


def test_config_parse_error_without_cause() -> None:
    exc = ConfigParseError("/abs/path.toml")
    assert exc.source_path == "/abs/path.toml"
    assert exc.cause is None
    assert "/abs/path.toml" in str(exc)


def test_config_validation_error_carries_attribution() -> None:
    exc = ConfigValidationError(
        "triggers.after_agent", "sometimes", "/abs/.harness-mem.toml"
    )
    assert exc.key_path == "triggers.after_agent"
    assert exc.value == "sometimes"
    assert exc.source_path == "/abs/.harness-mem.toml"
    msg = str(exc)
    assert "triggers.after_agent" in msg
    assert "sometimes" in msg
    assert "/abs/.harness-mem.toml" in msg
    assert isinstance(exc, ConfigError)


def test_isinstance_hierarchy() -> None:
    assert issubclass(ConfigPathError, ConfigError)
    assert issubclass(ConfigParseError, ConfigError)
    assert issubclass(ConfigValidationError, ConfigError)
    assert issubclass(ConfigError, Exception)


def test_import_from_package() -> None:
    # The four classes are importable from the package root.
    from harness_mem.config import (  # noqa: F401
        ConfigError as _CE,
        ConfigParseError as _CPE,
        ConfigPathError as _CPathE,
        ConfigValidationError as _CVE,
    )
