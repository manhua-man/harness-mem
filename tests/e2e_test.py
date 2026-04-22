"""E2E test: verify MemoryEntry and Observation write + read from SQLite."""

from __future__ import annotations
import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

# Add harness_mem to path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.core.schemas import Observation, MemoryEntry


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def backend(tmp_path: Path):
    data_dir = tmp_path / "data"
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        yield backend
    finally:
        run(backend.close())


async def _test_observation_roundtrip(backend: LocalMemoryBackend) -> bool:
    """Test: save observation -> get it back."""
    obs = Observation(
        session_id="session-001",
        client="claude-code",
        raw_content="Hello world, this is a test session transcript.",
        content_type="transcript",
        tags=["test", "e2e"],
    )

    saved_id = await backend.verbatim_store.save(obs)
    retrieved = await backend.verbatim_store.get(saved_id)

    assert retrieved is not None, "Observation should be retrievable"
    assert retrieved.id == obs.id
    assert retrieved.session_id == "session-001"
    assert retrieved.client == "claude-code"
    assert retrieved.raw_content == obs.raw_content
    assert retrieved.content_type == "transcript"
    assert "test" in retrieved.tags
    print(f"  [PASS] Observation roundtrip: id={saved_id}")
    return True


def test_observation_roundtrip(backend: LocalMemoryBackend):
    run(_test_observation_roundtrip(backend))


async def _test_memory_entry_roundtrip(backend: LocalMemoryBackend) -> bool:
    """Test: save memory entry -> get it back."""
    entry = MemoryEntry(
        project_name="test-project",
        category="architecture",
        content="Use sqlite-utils for FTS indexing in v1",
        confidence=0.9,
        source="manual",
        tags=["architecture", "sqlite"],
    )

    saved_id = await backend.structured_store.save_memory_entry(entry)
    retrieved = await backend.structured_store.get_memory_entry(saved_id)

    assert retrieved is not None, "MemoryEntry should be retrievable"
    assert retrieved.id == entry.id
    assert retrieved.project_name == "test-project"
    assert retrieved.category == "architecture"
    assert retrieved.content == entry.content
    assert retrieved.confidence == 0.9
    assert "architecture" in retrieved.tags
    print(f"  [PASS] MemoryEntry roundtrip: id={saved_id}")
    return True


def test_memory_entry_roundtrip(backend: LocalMemoryBackend):
    run(_test_memory_entry_roundtrip(backend))


async def _test_search(backend: LocalMemoryBackend) -> bool:
    """Test: save multiple -> search -> find."""
    # Save a searchable observation
    obs = Observation(
        session_id="session-002",
        client="codex",
        raw_content="The authentication system uses JWT tokens with RS256.",
        content_type="transcript",
        tags=["auth", "jwt"],
    )
    await backend.verbatim_store.save(obs)

    # Save a searchable memory entry
    entry = MemoryEntry(
        project_name="test-project",
        category="api",
        content="Auth endpoints accept Bearer tokens in Authorization header",
        confidence=0.95,
        source="manual",
    )
    await backend.structured_store.save_memory_entry(entry)

    # Search observations
    obs_results = await backend.verbatim_store.search("JWT")
    assert len(obs_results) >= 1, f"Should find JWT in observations, got {len(obs_results)}"
    print(f"  [PASS] Observation search: found {len(obs_results)} results for 'JWT'")

    # Search memory entries
    entry_results = await backend.structured_store.search_memory_entries("Auth")
    assert len(entry_results) >= 1, f"Should find Auth in memory entries, got {len(entry_results)}"
    print(f"  [PASS] MemoryEntry search: found {len(entry_results)} results for 'Auth'")
    return True


def test_search(backend: LocalMemoryBackend):
    run(_test_search(backend))


async def _test_timeline(backend: LocalMemoryBackend) -> bool:
    """Test: timeline returns observations in order."""
    for i in range(3):
        obs = Observation(
            session_id=f"session-timeline-{i}",
            client="claude-code",
            raw_content=f"Timeline test entry {i}",
            content_type="transcript",
        )
        await backend.verbatim_store.save(obs)

    timeline = await backend.verbatim_store.timeline(limit=5)
    assert len(timeline) >= 3, f"Should have at least 3 timeline entries, got {len(timeline)}"
    print(f"  [PASS] Timeline: got {len(timeline)} observations")
    return True


def test_timeline(backend: LocalMemoryBackend):
    run(_test_timeline(backend))


async def _test_structured_list(backend: LocalMemoryBackend) -> bool:
    """Test: list memory entries filtered by project."""
    # Save entries for different projects
    entry1 = MemoryEntry(
        project_name="proj-a",
        category="architecture",
        content="Project A architecture note",
        source="manual",
    )
    entry2 = MemoryEntry(
        project_name="proj-b",
        category="api",
        content="Project B API note",
        source="manual",
    )
    entry3 = MemoryEntry(
        project_name="proj-a",
        category="bug",
        content="Project A bug note",
        source="manual",
    )

    await backend.structured_store.save_memory_entry(entry1)
    await backend.structured_store.save_memory_entry(entry2)
    await backend.structured_store.save_memory_entry(entry3)

    # List all for proj-a
    proj_a_entries = await backend.structured_store.list_memory_entries("proj-a")
    assert len(proj_a_entries) >= 2, f"Should have 2+ entries for proj-a, got {len(proj_a_entries)}"
    print(f"  [PASS] List entries for proj-a: {len(proj_a_entries)} entries")

    # List filtered by category
    arch_entries = await backend.structured_store.list_memory_entries("proj-a", category="architecture")
    assert len(arch_entries) >= 1, f"Should have at least 1 architecture entry, got {len(arch_entries)}"
    print(f"  [PASS] List entries for proj-a (architecture): {len(arch_entries)} entries")
    return True


def test_structured_list(backend: LocalMemoryBackend):
    run(_test_structured_list(backend))


async def main():
    print("=== harness-mem E2E Test ===\n")

    # Use temp dir for isolation
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "data"
        backend = LocalMemoryBackend(data_dir)

        print("Initializing backend...")
        await backend.init()
        print(f"Data dir: {data_dir}\n")

        all_passed = True

        print("1. Testing Observation roundtrip...")
        try:
            await _test_observation_roundtrip(backend)
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            all_passed = False

        print("\n2. Testing MemoryEntry roundtrip...")
        try:
            await _test_memory_entry_roundtrip(backend)
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            all_passed = False

        print("\n3. Testing search...")
        try:
            await _test_search(backend)
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            all_passed = False

        print("\n4. Testing timeline...")
        try:
            await _test_timeline(backend)
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            all_passed = False

        print("\n5. Testing structured list...")
        try:
            await _test_structured_list(backend)
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            all_passed = False

        await backend.close()

    print("\n" + "=" * 40)
    if all_passed:
        print("ALL TESTS PASSED")
        return 0
    else:
        print("SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
