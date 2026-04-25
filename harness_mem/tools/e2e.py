"""Package-level E2E smoke checks for the local memory backend."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from harness_mem.core.schemas import MemoryEntry, Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


async def check_observation_roundtrip(
    backend: LocalMemoryBackend,
    *,
    verbose: bool = True,
) -> None:
    """Save an observation and verify it can be read back."""
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
    if verbose:
        print(f"  [PASS] Observation roundtrip: id={saved_id}")


async def check_memory_entry_roundtrip(
    backend: LocalMemoryBackend,
    *,
    verbose: bool = True,
) -> None:
    """Save a memory entry and verify it can be read back."""
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
    if verbose:
        print(f"  [PASS] MemoryEntry roundtrip: id={saved_id}")


async def check_search(
    backend: LocalMemoryBackend,
    *,
    verbose: bool = True,
) -> None:
    """Save searchable records and verify search can retrieve them."""
    obs = Observation(
        session_id="session-002",
        client="codex",
        raw_content="The authentication system uses JWT tokens with RS256.",
        content_type="transcript",
        tags=["auth", "jwt"],
    )
    await backend.verbatim_store.save(obs)

    entry = MemoryEntry(
        project_name="test-project",
        category="api",
        content="Auth endpoints accept Bearer tokens in Authorization header",
        confidence=0.95,
        source="manual",
    )
    await backend.structured_store.save_memory_entry(entry)

    obs_results = await backend.verbatim_store.search("JWT")
    assert len(obs_results) >= 1, f"Should find JWT in observations, got {len(obs_results)}"

    entry_results = await backend.structured_store.search_memory_entries("Auth")
    assert len(entry_results) >= 1, f"Should find Auth in memory entries, got {len(entry_results)}"

    if verbose:
        print(f"  [PASS] Observation search: found {len(obs_results)} results for 'JWT'")
        print(f"  [PASS] MemoryEntry search: found {len(entry_results)} results for 'Auth'")


async def check_timeline(
    backend: LocalMemoryBackend,
    *,
    verbose: bool = True,
) -> None:
    """Save several observations and verify timeline ordering works."""
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
    if verbose:
        print(f"  [PASS] Timeline: got {len(timeline)} observations")


async def check_structured_list(
    backend: LocalMemoryBackend,
    *,
    verbose: bool = True,
) -> None:
    """Save entries for multiple projects and verify filtering works."""
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

    proj_a_entries = await backend.structured_store.list_memory_entries("proj-a")
    assert len(proj_a_entries) >= 2, f"Should have 2+ entries for proj-a, got {len(proj_a_entries)}"

    arch_entries = await backend.structured_store.list_memory_entries("proj-a", category="architecture")
    assert len(arch_entries) >= 1, f"Should have at least 1 architecture entry, got {len(arch_entries)}"

    if verbose:
        print(f"  [PASS] List entries for proj-a: {len(proj_a_entries)} entries")
        print(f"  [PASS] List entries for proj-a (architecture): {len(arch_entries)} entries")


E2E_CHECKS = [
    ("Observation roundtrip", check_observation_roundtrip),
    ("MemoryEntry roundtrip", check_memory_entry_roundtrip),
    ("Search", check_search),
    ("Timeline", check_timeline),
    ("Structured list", check_structured_list),
]


async def run_e2e_smoke(
    data_dir: Path | None = None,
    *,
    verbose: bool = True,
) -> int:
    """Run the backend smoke suite against a temporary or provided data dir."""
    temp_dir_cm = tempfile.TemporaryDirectory() if data_dir is None else None
    if temp_dir_cm is not None:
        root = Path(temp_dir_cm.name) / "data"
    else:
        assert data_dir is not None
        root = Path(data_dir)
    backend = LocalMemoryBackend(root)

    if verbose:
        print("=== harness-mem E2E Test ===\n")
        print("Initializing backend...")

    await backend.init()

    try:
        if verbose:
            print(f"Data dir: {root}\n")

        all_passed = True
        for idx, (label, check) in enumerate(E2E_CHECKS, start=1):
            if verbose:
                print(f"{idx}. Testing {label}...")
            try:
                await check(backend, verbose=verbose)
            except AssertionError as exc:
                if verbose:
                    print(f"  [FAIL] {exc}")
                all_passed = False
            if verbose and idx < len(E2E_CHECKS):
                print()

        if verbose:
            print("\n" + "=" * 40)
            print("ALL TESTS PASSED" if all_passed else "SOME TESTS FAILED")

        return 0 if all_passed else 1
    finally:
        await backend.close()
        if temp_dir_cm is not None:
            temp_dir_cm.cleanup()


def main() -> int:
    """Run the E2E smoke suite as a module entrypoint."""
    return asyncio.run(run_e2e_smoke())


if __name__ == "__main__":
    raise SystemExit(main())
