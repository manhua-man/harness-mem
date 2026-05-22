"""Loop harness scenario 6 — relation graph data pipeline reality check.

Question answered: "does the heuristic distill pipeline actually feed the
relation graph with usable data, or does v1.7.2 graph traversal sit on
top of a permanently empty table?"

Background: v1.7.2 shipped bounded relation-path traversal exposed via
``trace_relations`` (CLI + MCP). The promise is that wake-up and search
can walk relation edges to surface "X depends_on Y" style facts. But
the producer side of that graph is the heuristic ``RELATION_FACT_PATTERNS``
in ``adapters/parser.py``, which requires:

- both entity tokens to start with uppercase letters
- one of six fixed relation verbs ("depends on", "relies on",
  "delegates to", "calls into", "uses", "backs onto")
- the whole match to fit in a single sentence

Real Claude Code session prose almost never satisfies all three. So
``trace_relations`` is technically functional but practically empty
unless an LLM-driven distiller (or a manual ``suggest_relation_fact``
caller) feeds the table.

This scenario uses two paired sub-tests to make that gap visible:

1. Run distill over the loop_harness's natural-style fixtures (the same
   ones scenario 1/2 use). Assert that the heuristic relation extractor
   produces effectively zero relation facts. The number printed is the
   evidence.
2. Run distill over a hand-crafted fixture that is grammatically
   tailored to the patterns. Assert that *those* sentences do produce
   relation facts. This proves the extractor isn't broken — it's just
   too strict for real prose.

Together they say: "graph traversal is shipped, the producer is shipped,
but the wiring between heuristic distill and the graph table is
practically dead in the absence of an LLM-driven distiller."
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import patch_cli_adapters, run, write_claude_session
from tests.loop_harness.conftest import LoopMetrics
from tests.loop_harness.fixtures import LOOP_FIXTURES

pytestmark = pytest.mark.loop_harness


def test_natural_session_fixtures_produce_no_relation_facts(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    claude_sessions_root_with_fixtures: Path,
):
    """The fixtures from scenario 1/2 should generate ~zero relation facts.

    This is the reality check: the same prose that yields healthy
    MemoryEntry extraction (scenario 1 reports F1 ≈ 0.91) yields almost
    nothing for the relation graph. That asymmetry is the gap.
    """
    patch_cli_adapters(
        monkeypatch, claude_sessions_root=claude_sessions_root_with_fixtures
    )

    project_name = LOOP_FIXTURES[0].project_name
    assert run(cli.cmd_distill(project_name, auto_confirm=True)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        memory_entries = run(
            backend.structured_store.list_memory_entries(project_name, limit=200)
        )
        relation_facts = run(
            backend.structured_store.list_relation_facts(project_name, limit=200)
        )
    finally:
        run(backend.close())

    LoopMetrics(
        name="relation_graph_data_pipeline_natural",
        values={
            "memory_entries_extracted": float(len(memory_entries)),
            "relation_facts_extracted": float(len(relation_facts)),
            "relation_to_memory_ratio": (
                float(len(relation_facts)) / max(1, len(memory_entries))
            ),
        },
    ).report()

    # The asymmetry is the finding. We expect plenty of memory entries
    # and effectively no relation facts from prose-shaped sessions.
    assert len(memory_entries) > 0, (
        "scenario regression: heuristic distill stopped extracting memory entries"
    )
    # Allow up to one accidental relation match — the patterns can fire
    # if a fixture happens to drop a 'X depends on Y' into prose. The
    # point is that this is the floor, not the rule.
    assert len(relation_facts) <= 1, (
        f"unexpected relation extraction from natural prose: "
        f"{len(relation_facts)} facts. Heuristic patterns may have been "
        f"loosened — re-evaluate this scenario's expectations."
    )


def test_relation_friendly_session_does_produce_relation_facts(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """A hand-crafted session that matches RELATION_FACT_PATTERNS still works.

    This guards against silently breaking the relation extractor while
    lowering noise: if someone tightens the patterns further or removes
    one of the six relation verbs, this test is the canary.
    """
    sessions_root = tmp_path / "claude-projects-relation"
    project_name = "relation-pipeline-check"

    write_claude_session(
        sessions_root,
        project_name,
        "sess-relation-friendly-001",
        "Walk me through how the new ingest layer is wired.",
        [
            # Hand-shaped to match each of the three relation-fact patterns
            # in adapters/parser.py: depends_on, delegates_to, uses.
            "The IngestRouter depends on SessionAdapter for normalizing "
            "raw transcripts into Observation objects.",
            "When the user calls /hm:distill, IngestRouter delegates to "
            "DistillContext for any candidate-layer writes.",
            "DistillContext uses StructuredStore as the backing store; "
            "this keeps the heuristic adapter free of mutator concerns.",
        ],
    )

    patch_cli_adapters(monkeypatch, claude_sessions_root=sessions_root)
    assert run(cli.cmd_distill(project_name, auto_confirm=True)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        relation_facts = run(
            backend.structured_store.list_relation_facts(project_name, limit=200)
        )
    finally:
        run(backend.close())

    relation_types_found = {fact.relation_type for fact in relation_facts}
    LoopMetrics(
        name="relation_graph_data_pipeline_friendly",
        values={
            "relation_facts_extracted": float(len(relation_facts)),
            "distinct_relation_types": float(len(relation_types_found)),
        },
    ).report()

    # Hand-crafted prose hits all three relation verbs. We assert at
    # least two land — being conservative against future pattern tweaks
    # that might drop one verb.
    assert len(relation_facts) >= 2, (
        f"hand-crafted relation-friendly prose produced too few facts: "
        f"{len(relation_facts)}. Either relation patterns regressed "
        f"or the fixture grammar drifted."
    )
    assert len(relation_types_found) >= 2, (
        f"hand-crafted prose covered three patterns but only "
        f"{len(relation_types_found)} relation_types were extracted; "
        f"verify each of depends_on / delegates_to / uses still fires."
    )
