"""LocalProjectProfileStore — JSON file implementation of ProjectProfileStore."""

from __future__ import annotations
import asyncio
import json
from pathlib import Path

from harness_mem.core.interfaces.project_profile_store import ProjectProfileStore
from harness_mem.core.schemas.project_profile import ProjectProfile


class LocalProjectProfileStore:
    """Project profile store backed by JSON files.

    Profiles stored at: data_dir/profiles/{project_name}.json
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.profiles_dir = self.data_dir / "profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    def _profile_path(self, project_name: str) -> Path:
        safe = project_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self.profiles_dir / f"{safe}.json"

    async def save(self, profile: ProjectProfile) -> str:
        path = self._profile_path(profile.project_name)
        path.write_text(json.dumps(profile.to_dict(), indent=2, default=str))
        return profile.id

    async def get(self, project_name: str) -> ProjectProfile | None:
        path = self._profile_path(project_name)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return ProjectProfile.from_dict(data)

    async def list(self) -> list[ProjectProfile]:
        results = []
        for path in self.profiles_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                results.append(ProjectProfile.from_dict(data))
            except (json.JSONDecodeError, ValueError):
                continue
        return sorted(results, key=lambda p: p.project_name)
