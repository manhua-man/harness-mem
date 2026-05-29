"""harness_mem.config — configuration loading + merging for v2.4.1.

Re-exports the config error hierarchy so callers can
``from harness_mem.config import ConfigError`` without reaching into the
``errors`` submodule.
"""

from harness_mem.config.errors import (
    ConfigError,
    ConfigParseError,
    ConfigPathError,
    ConfigValidationError,
)

__all__ = [
    "ConfigError",
    "ConfigPathError",
    "ConfigParseError",
    "ConfigValidationError",
]
