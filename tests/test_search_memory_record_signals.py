"""Opt-out unit tests for the v2.5.0 ``record_signals`` keyword.

``read_api.search_memory`` shadow-writes one ``search_hit``
``RetrievalSignal`` per returned entry by default. The v2.5.0
Plan_Assembler needs a side-effect-free read, so ``search_memory`` grew a
``record_signals: bool = True`` keyword. These tests pin both halves of
the contract:

* ``record_signals=False`` emits **zero** ``search_hit`` signals while
  returning the same entries/observations as the default call.
* The default call (no keyword) still writes ``search_hit`` signals.

Requirements: 5.6, 9.2
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from harness_mem.core.schemas import MemoryEntry, Observation
from harness_mem.read_api import search_memory
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


_QUERY = "SQLite FTS5"


def _seed_search_corpus(backend: LocalMemoryBackend, project_name: str) -> str:
    """Seed one accepted entry + one observation matching ``_QUERY``.

    Mirrors the proven seed used by the v2.3 ``search_hit`` test so the
    query returns at least one entry (and therefore would emit at least
    one signal under default behavior).
    """
    observation = Observation(
        session_id=f"sess-{uuid4().hex[:8]}",
        client="claude-code",
        raw_content=(
            "We use SQLite FTS5 with porter tokenizer for full-text search "
            "across structured memory entries."
        ),
        content_type="transcript",
        metadata={"project_name": project_name},
        tags=["session", "claude-code"],
    )
    run(backend.verbatim_store.save(observation))

    entry = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content=(
            "SQLite FTS5 is used for full-text search indexing in this project."
        ),
        confidence=0.9,
        source="obs-seed",
        status="accepted",
        tags=["architecture", "search"],
    )
    return run(backend.structured_store.save_memory_entry(entry))


def test_record_signals_false_emits_no_search_hit_and_matches_default(
    data_dir: Path,
) -> None:
    """``record_signals=False`` writes no signals yet returns identical results."""
    project_name = "rec-signals-optout"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entry_id = _seed_search_corpus(backend, project_name)

        # Baseline: empty signal table before any search.
        assert (
            run(
                backend.structured_store.query_retrieval_signals(
                    project_name, signal_type="search_hit"
                )
            )
            == []
        )

        # Opt-out call must return hits but write zero signals.
        optout_entries, optout_observations = run(
            search_memory(
                backend,
                project_name=project_name,
                query=_QUERY,
                memory_entry_limit=20,
                observation_limit=20,
                record_signals=False,
            )
        )
        assert any(entry.id == entry_id for entry in optout_entries)

        signals_after_optout = run(
            backend.structured_store.query_retrieval_signals(
                project_name, signal_type="search_hit"
            )
        )
        assert signals_after_optout == [], (
            "record_signals=False must not write any search_hit signal"
        )

        # Default call returns the same entries/observations as the opt-out call.
        default_entries, default_observations = run(
            search_memory(
                backend,
                project_name=project_name,
                query=_QUERY,
                memory_entry_limit=20,
                observation_limit=20,
            )
        )
    finally:
        run(backend.close())

    assert [entry.id for entry in optout_entries] == [
        entry.id for entry in default_entries
    ]
    assert [obs.id for obs in optout_observations] == [
        obs.id for obs in default_observations
    ]


def test_default_search_memory_still_writes_search_hit_signals(
    data_dir: Path,
) -> None:
    """The default call (no ``record_signals`` kwarg) keeps emitting signals."""
    project_name = "rec-signals-default"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entry_id = _seed_search_corpus(backend, project_name)

        entries, _observations = run(
            search_memory(
                backend,
                project_name=project_name,
                query=_QUERY,
                memory_entry_limit=20,
            )
        )
        assert any(entry.id == entry_id for entry in entries)

        signals = run(
            backend.structured_store.query_retrieval_signals(
                project_name, signal_type="search_hit"
            )
        )
    finally:
        run(backend.close())

    assert signals, "default search_memory must still write search_hit signals"
    target_ids = [signal.target_id for signal in signals]
    assert entry_id in target_ids
    matched = next(signal for signal in signals if signal.target_id == entry_id)
    assert matched.target_kind == "memory_entry"
    assert matched.context == {"query": _QUERY}
