from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness_mem import cli, event_log  # noqa: E402
from harness_mem.commands import doctor, maintenance, profile, purge, search, wake  # noqa: E402
from harness_mem.commands import ingest, onboarding  # noqa: E402
from harness_mem.commands import status  # noqa: E402
from harness_mem.commands import support as command_support  # noqa: E402
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402
from tests.helpers import run  # noqa: E402


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(cli, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(command_support, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(doctor, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(ingest, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(maintenance, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(onboarding, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(profile, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(purge, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(status, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(wake, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(search, "DEFAULT_DATA_DIR", data_dir)
    event_log._event_logger = None
    try:
        yield data_dir
    finally:
        event_log._event_logger = None


@pytest.fixture
def backend(data_dir: Path) -> LocalMemoryBackend:
    local_backend = LocalMemoryBackend(data_dir)
    run(local_backend.init())
    try:
        yield local_backend
    finally:
        run(local_backend.close())


@pytest.fixture
def claude_sessions_root(tmp_path: Path) -> Path:
    return tmp_path / "claude-projects"


@pytest.fixture
def codex_sessions_root(tmp_path: Path) -> Path:
    path = tmp_path / "codex-sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path
