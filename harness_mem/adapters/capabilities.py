"""Explicit capture and native-cleanup capabilities for host adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.native_source_cleanup import cleanup_native_source

CaptureMode = Literal["file", "shared_container", "mixed"]
NativeCleanupMode = Literal["file", "source_dependent", "unsupported"]


@dataclass(frozen=True)
class AdapterCapabilities:
    """Stable host capability row used by qualification and cleanup callers."""

    capture_mode: CaptureMode
    native_cleanup_mode: NativeCleanupMode

    def cleanup_native_source(
        self,
        source: TranscriptSource,
        *,
        quiet_seconds: int = 60,
    ) -> dict:
        """Delegate cleanup to the single fail-closed native cleanup implementation."""

        return cleanup_native_source(source, quiet_seconds=quiet_seconds)

    def to_dict(self) -> dict[str, str]:
        """Return the serializable capability fields used in replay reports."""

        return {
            "capture_mode": self.capture_mode,
            "native_cleanup_mode": self.native_cleanup_mode,
        }


__all__ = ["AdapterCapabilities", "CaptureMode", "NativeCleanupMode"]
