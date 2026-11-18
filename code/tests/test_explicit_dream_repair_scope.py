"""Explicit maintenance selects immutable groups and never adopts old accounts."""
from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace as NS

import pytest

from harness_mem.commands import dream, dream_source_coverage as coverage_owner
from harness_mem.core.schemas import KnowledgeEntry
from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage
from test_terminal_source_coverage import terminal as terminal


def run(value):
    return asyncio.run(value)


@pytest.fixture
def scope_store(tmp_path, monkeypatch):
    entries = {name: KnowledgeEntry(id=name, project_name="demo", title=name,
        statement="A source-backed scoped fact.", module_path=["topic"])
        for name in ["report", "duplicate-a", "duplicate-b"]}
    sources = {name: [NS(to_dict=lambda name=name: {"id": "source-" + name})] for name in entries}

    async def get(identity, *, project_name, project_root):
        return entries.get(identity)

    async def list_sources(identity):
        return sources.get(identity, [])

    async def prepare(_backend, **kwargs):
        return {"contract": "fixture-source-repair", "predecessor_ids": kwargs["predecessor_ids"],
                "run_id": kwargs["run_id"], "origin_run_id": kwargs["origin_run_id"]}

    monkeypatch.setattr(coverage_owner, "prepare_explicit_source_repair", prepare, raising=False)
    backend = NS(structured_store=NS(knowledge_store=NS(get_entry=get, list_sources=list_sources)))
    scope = {"source": {"origin_run_id": "old-failed", "predecessor_ids": ["old-predecessor"]},
             "groups": [{"kind": "stale", "target_ids": ["report"]},
                        {"kind": "duplicate", "target_ids": ["duplicate-a", "duplicate-b"]}]}
    return backend, tmp_path, entries, sources, scope


def freeze(fixture, scope=None):
    backend, root, _entries, _sources, original = fixture
    return run(dream._freeze_explicit_repair_scope(backend, project_name="demo",
        project_root=root, run_id="new-repair", scope=scope if scope is not None else original))


def test_explicit_scope_keeps_order_and_only_binds_original_targets(scope_store):
    original = copy.deepcopy(scope_store[-1])
    manifest = freeze(scope_store)
    assert manifest["source"]["run_id"] == "new-repair"
    assert manifest["source"]["origin_run_id"] == "old-failed"
    assert [row["kind"] for row in manifest["groups"]] == ["stale", "duplicate"]
    assert [row["target_ids"] for row in manifest["groups"]] == [["report"], ["duplicate-a", "duplicate-b"]]
    assert all(set(target) == {"id", "fingerprint", "sources_sha256"}
        for group in manifest["groups"] for target in group["targets"])
    assert scope_store[-1] == original


@pytest.mark.parametrize("fault", ["foreign", "missing", "missing_source", "repeated", "singleton_duplicate", "prose", "empty"])
def test_invalid_scopes_refuse_before_any_semantic_operation(scope_store, fault):
    scope = copy.deepcopy(scope_store[-1])
    entries, sources = scope_store[2:4]
    if fault == "foreign":
        entries["report"].project_name = "other"
    elif fault == "missing":
        entries.pop("report")
    elif fault == "missing_source":
        sources["report"] = []
    elif fault == "repeated":
        scope["groups"].append({"kind": "stale", "target_ids": ["report"]})
    elif fault == "singleton_duplicate":
        scope["groups"][1]["target_ids"] = ["duplicate-a"]
    elif fault == "prose":
        scope["groups"][0]["replacement"] = "A manually supplied replacement."
    else:
        scope = {"groups": []}
    with pytest.raises(ValueError):
        freeze(scope_store, scope)


@pytest.mark.parametrize("change", ["statement", "sources"])
def test_pending_target_or_source_changes_refuse_but_completed_groups_do_not_replay(scope_store, change):
    backend, root, entries, sources, _scope = scope_store
    manifest = freeze(scope_store)
    if change == "statement":
        entries["report"].statement += " Changed later."
    else:
        sources["report"] = []
    with pytest.raises(ValueError, match="dream_repair_target_changed"):
        run(dream._assert_explicit_repair_targets(backend, project_name="demo", project_root=root,
            scope=manifest, completed_indexes=set()))
    run(dream._assert_explicit_repair_targets(backend, project_name="demo", project_root=root,
        scope=manifest, completed_indexes={0}))


def test_a_fresh_target_only_repair_is_valid(scope_store):
    manifest = freeze(scope_store, {"groups": scope_store[-1]["groups"]})
    assert manifest["source"] is None and len(manifest["groups"]) == 2


@pytest.mark.parametrize("confirmation_only", [False, True])
def test_fresh_dream_runs_source_pipeline_before_groups_without_old_takeover(terminal, monkeypatch, confirmation_only):
    from harness_mem.autonomous.executors.task_budget import read_task_budget_receipt
    backend, root, old, _carrier, _job, provider, config, bindings = terminal
    monkeypatch.setattr("harness_mem.config.merge.load_merged_config", lambda _: config)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Explicit repair must not invoke ordinary selection or old-account takeover")
    monkeypatch.setattr(dream, "_detect_separated_rechecks", forbidden)
    monkeypatch.setattr(coverage_owner, "run_pending_terminal_source_coverage", forbidden)
    before = backend.structured_store._canonical.get_payload_json("dream_runs", old.id)
    old_account = copy.deepcopy(read_task_budget_receipt(backend.data_dir, bindings[0].task_scope))
    provider.confirm = confirmation_only
    result = run(dream.dream_once(backend, project_name="demo", project_root=root, config=config,
        source="agent", host_client=provider.host_client, semantic_provider=provider,
        repair_scope={"source": {"origin_run_id": old.id, "predecessor_ids": [old.items[0].source_id]},
            "groups": ([{"kind": "stale", "target_ids": ["narrow-successor"]}] if confirmation_only else [])}))
    assert result.status == ("failed" if confirmation_only else "completed")
    assert result.continuation["explicit_source_repair_result"]["status"] == ("no_write" if confirmation_only else "applied")
    assert result.continuation["completed_signal_indexes"] == []
    assert backend.structured_store._canonical.get_payload_json("dream_runs", old.id) == before
    assert read_task_budget_receipt(backend.data_dir, bindings[0].task_scope) == old_account
    assert provider.task_budget_binding.task_scope != bindings[0].task_scope
    assert result.continuation["max_slices"] >= 3
