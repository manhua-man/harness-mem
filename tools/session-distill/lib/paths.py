"""Path helpers for the session-distill specialization."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DistillPaths:
    """Resolved working paths for session-distill artifacts."""

    root: Path
    packets: Path
    distilled_sessions: Path
    memory_drafts: Path


def default_distill_root() -> Path:
    env_dir = os.environ.get("SESSION_DISTILL_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".codex" / "session-distill"


def resolve_distill_paths(root: Path | None = None) -> DistillPaths:
    base = root or default_distill_root()
    return DistillPaths(
        root=base,
        packets=base / "packets",
        distilled_sessions=base / "distilled" / "sessions",
        memory_drafts=base / "memory-drafts",
    )


def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent
