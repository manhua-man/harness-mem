"""Tests for the v1.6.1 distill read-only boundary (DistillContext)."""

from __future__ import annotations

import pytest

from harness_mem.core.schemas import MemoryEntry, RelationFact
from harness_mem.distill_context import DistillContext, DistillReadOnlyError
from tests.helpers import run


def test_distill_context_exposes_no_mutator_attrs(backend) -> None:
    ctx = DistillContext(backend)
    public_methods = [
        name for name in dir(ctx)
        if not name.startswith("_")
    ]
    forbidden = [
        name
        for name in public_methods
        if any(kw in name.lower() for kw in ("delete", "purge", "mutate", "drop"))
        and not name.startswith("suggest_")
    ]
    assert forbidden == [], f"DistillContext leaks mutator-shaped attrs: {forbidden}"

    update_attrs = [
        name
        for name in public_methods
        if "update" in name.lower() and not name.startswith("suggest_")
    ]
    assert update_attrs == [], f"DistillContext leaks update-shaped attrs: {update_attrs}"


def test_distill_context_blocks_dynamic_mutator_access(backend) -> None:
    ctx = DistillContext(backend)
    with pytest.raises(DistillReadOnlyError) as excinfo:
        ctx.delete_memory_entry  # noqa: B018
    assert excinfo.value.method == "delete_memory_entry"
    assert "suggest_memory_entry" in excinfo.value.hint

    with pytest.raises(DistillReadOnlyError):
        ctx.update_relation_fact_status  # noqa: B018

    with pytest.raises(DistillReadOnlyError):
        ctx.purge_observations  # noqa: B018


def test_distill_context_unknown_attr_still_raises_attribute_error(backend) -> None:
    ctx = DistillContext(backend)
    with pytest.raises(AttributeError):
        ctx.totally_unrelated  # noqa: B018


def test_suggest_memory_entry_persists_pending(backend) -> None:
    ctx = DistillContext(backend)
    entry = MemoryEntry(
        project_name="demo",
        category="convention",
        content="use single quote",
        source="obs_1",
    )
    saved = run(ctx.suggest_memory_entry(entry))
    assert saved.status == "pending"

    pending = run(
        backend.structured_store.search_memory_entries(
            "single quote", project_name="demo", status="pending"
        )
    )
    assert len(pending) == 1
    assert pending[0].id == entry.id

    accepted = run(
        backend.structured_store.search_memory_entries(
            "single quote", project_name="demo", status="accepted"
        )
    )
    assert accepted == []


def test_suggest_relation_fact_persists_pending(backend) -> None:
    ctx = DistillContext(backend)
    fact = RelationFact(
        project_name="demo",
        source_entity="harness-mem",
        relation_type="uses",
        target_entity="sqlite-fts5",
        evidence="we decided to use sqlite-fts5",
        source="obs_1",
    )
    saved = run(ctx.suggest_relation_fact(fact))
    assert saved.status == "pending"

    fetched = run(backend.structured_store.get_relation_fact(fact.id))
    assert fetched is not None
    assert fetched.status == "pending"

    accepted = run(
        backend.structured_store.list_relation_facts(
            "demo", limit=10, status="accepted"
        )
    )
    assert all(f.id != fact.id for f in accepted), (
        "pending relation_fact must not appear in default (status='accepted') listing"
    )


def test_auto_confirm_via_status_mutator_flips_status(backend) -> None:
    """v2.0: pending entries become accepted via update_*_status mutators.

    Before v2.0 there was a CLI helper ``_confirm_pending_outputs`` that
    bridged ``--auto-confirm`` to the structured store. v2.0 removed the
    heuristic distill code path entirely (along with that helper), so
    callers that need to flip pending entries to accepted go straight
    through the structured store. The DistillContext itself still
    refuses to mutate truth — that boundary is the point.
    """
    ctx = DistillContext(backend)
    entry = MemoryEntry(
        project_name="demo",
        category="convention",
        content="prefer plain dataclasses",
        source="obs_2",
    )
    run(ctx.suggest_memory_entry(entry))

    # Direct mutator call: this is what an MCP tool (e.g. confirm_memory_entry)
    # or any future auto-review applier would do. DistillContext is bypassed
    # here on purpose — its job is producing candidates, not promoting them.
    flipped = run(
        backend.structured_store.update_memory_entry_status(entry.id, "accepted")
    )
    assert flipped is True

    accepted = run(
        backend.structured_store.search_memory_entries(
            "plain dataclasses", project_name="demo", status="accepted"
        )
    )
    assert any(e.id == entry.id for e in accepted)


def test_distill_context_does_not_expose_auto_confirm(backend) -> None:
    """auto-confirm 是 CLI 兼容路径，不应出现在 DistillContext API 表面。"""
    ctx = DistillContext(backend)
    assert not hasattr(type(ctx), "auto_confirm_pending"), (
        "DistillContext must not expose auto_confirm_pending — that bypasses "
        "the candidate boundary; route through commands/distill helpers instead."
    )


def test_distill_context_compare_returns_diff_summary(backend) -> None:
    ctx = DistillContext(backend)
    left = MemoryEntry(
        project_name="demo",
        category="convention",
        content="left content",
        source="obs",
    )
    right = MemoryEntry(
        project_name="demo",
        category="convention",
        content="right content",
        source="obs",
    )
    a, b, diff = ctx.compare(left, right)
    assert a is left and b is right
    assert diff == {"content_changed": True, "category_changed": False}
