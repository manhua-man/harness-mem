"""Repository-truth checks for stale version/release claims."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from harness_mem.storage.local_memory_backend import LocalMemoryBackend

_VERSION_PATTERN = re.compile(r"\bv?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\b")
_VERSION_CLAIM_PATTERN = re.compile(
    r"\b(?:current|latest|version|released?|published?|shipped?|tagged?)\b",
    re.IGNORECASE,
)


def current_project_version(
    backend: LocalMemoryBackend,
    project_name: str,
) -> str | None:
    """Read current version from the active repository, never from memory."""

    sources = backend.transcript_store.list_sources(project_name=project_name, limit=1)
    if not sources:
        return None
    return project_version_from_root(Path(str(sources[0].project_root)))


def project_version_from_root(project_root: Path) -> str | None:
    pyproject = project_root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    project = data.get("project")
    if isinstance(project, dict) and isinstance(project.get("version"), str):
        return str(project["version"])
    return None


def version_conflict_reason(value: str, *, current_version: str | None) -> str | None:
    """Explain a release/version claim contradicted by current repo truth."""

    if not current_version or not _VERSION_CLAIM_PATTERN.search(value):
        return None
    versions = {match.group(1) for match in _VERSION_PATTERN.finditer(value)}
    conflicting = sorted(version for version in versions if version != current_version)
    if not conflicting:
        return None
    return (
        f"mentions version/release {', '.join(conflicting[:3])}; "
        f"current repository version is {current_version}"
    )


__all__ = [
    "current_project_version",
    "project_version_from_root",
    "version_conflict_reason",
]
