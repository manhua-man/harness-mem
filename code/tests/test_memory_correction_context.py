"""Current correction ownership and source context use the existing native loop."""
from __future__ import annotations

import asyncio
import json

import pytest

from harness_mem.commands.knowledge_assimilation import (
    KnowledgeTargetError,
    resolve_knowledge_target_project,
)
from harness_mem.commands.session_inventory import prepare_correction_source
from harness_mem.mcp import tool_handlers
from test_device_memory_flow import device as device, remember


def test_correction_resolves_device_owner_and_raw_read_includes_current_evidence(device):
    backend, write = device
    original = "Lantern club: keep original book titles; only use verified page numbers. Author naming is undecided."
    correction = "Book titles now use a translation followed by the original. Other requirements stay unchanged; author naming is still undecided."
    current = "Lantern club: use translated book titles followed by the original; only use verified page numbers. Author naming is undecided."
    first = write("lantern-original", original)
    packet = tool_handlers.tool_prepare_session_distill(client="codex", scope="all", session_id="lantern-original")
    remember(backend, packet, original)
    old = tool_handlers.tool_search_memory(query="Lantern")["memories"][0]
    second = write("lantern-correction", correction)
    originals = {path: path.read_bytes() for path in (first, second)}

    packet = tool_handlers.tool_prepare_session_distill(
        client="codex", session_id="lantern-correction", target_knowledge=[old],
    )
    assert packet["success"] and packet["project_name"] == "global", packet
    saved = remember(backend, packet, current, disposition="replace", targets=[old])
    assert saved["readback_verified"] is True

    evidence = tool_handlers.tool_search_raw(pattern="Lantern", scope="all")
    assert evidence["count"] == 1  # The correction does not repeat this search word.
    assert "keep original book titles" in evidence["matches"][0]["snippet"]
    context = evidence["current_knowledge"]
    assert len(context) == 1 and context[0]["statement"] == current
    assert context[0]["source_status"] == "verified"
    assert correction in context[0]["source_evidence"][0]["content"]
    assert "unresolved current conflict" in evidence["evidence_note"]
    assert tool_handlers.tool_search_memory(query="Lantern")["memories"][0]["statement"] == current
    assert all(path.read_bytes() == content for path, content in originals.items())
    old_value = tool_handlers.tool_search_raw(pattern="keep original book titles", scope="all")
    assert len(old_value["matches"]) == 1
    assert [item["statement"] for item in old_value["current_knowledge"]] == [current]
    assert correction in old_value["current_knowledge"][0]["source_evidence"][0]["content"]


def test_correction_target_chooses_unique_project_and_rejects_changed_or_ambiguous_text():
    from types import SimpleNamespace

    rows = {
        "club": [SimpleNamespace(id="c", title="Loan rule", statement="Five days", module_path=["Loans"])],
        "other": [SimpleNamespace(id="o", title="Loan rule", statement="Three days", module_path=["Loans"])],
    }

    class Store:
        async def known_projects(self):
            return list(rows)

        async def list_entries(self, project_name):
            return rows[project_name]

    store = Store()
    assert asyncio.run(resolve_knowledge_target_project(store, [{"title": "Loan rule", "statement": "Five days"}])) == "club"
    for target in ([{"title": "Loan rule"}], [{"statement": "Changed meanwhile"}], []):
        with pytest.raises(KnowledgeTargetError):
            asyncio.run(resolve_knowledge_target_project(store, target))


def test_project_correction_uses_target_owner_across_native_workspaces(device, tmp_path):
    backend, write = device
    original = "For future club loans, allow three days; the deposit remains undecided."
    write("club-original", original, roots=[tmp_path / "old-workspace"])
    job = prepare_correction_source(backend, project_name="club", client="codex", session_id="club-original")
    packet = tool_handlers.tool_prepare_session_distill(project_name="club", distill_job_id=job.id)
    remember(backend, packet, original)
    old = tool_handlers.tool_search_memory(query="club")["memories"][0]
    assert old["project_name"] == "club"
    correction = "For future club loans, allow five days; the deposit remains undecided."
    write("club-correction", correction, roots=[tmp_path / "another-workspace"])
    packet = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="club-correction", target_knowledge=[old],
    )
    assert packet["success"] and packet["project_name"] == "club", packet
    remember(backend, packet, correction, disposition="replace", targets=[old])
    current = tool_handlers.tool_search_memory(query="club")["memories"]
    assert len(current) == 1 and current[0]["statement"] == correction
    assert not asyncio.run(backend.structured_store.knowledge_store.list_entries("global"))


@pytest.mark.parametrize("run_ingest,excluded", [(False, False), (True, True)])
def test_targeted_correction_keeps_ingest_and_source_capture_policy(device, tmp_path, monkeypatch, run_ingest, excluded):
    from harness_mem.commands import session_inventory
    from harness_mem.config.merge import MergedConfig

    backend, write = device
    write("initial", "For future use, the deposit remains undecided.")
    packet = tool_handlers.tool_prepare_session_distill(client="codex", scope="all", session_id="initial")
    remember(backend, packet, "The deposit remains undecided.")
    old = tool_handlers.tool_search_memory(query="")["memories"][0]
    root = tmp_path / "restricted"
    root.mkdir()
    write("correction", "The deposit is now fifty.", roots=[root])
    if excluded:
        monkeypatch.setattr(session_inventory, "load_merged_config", lambda path: MergedConfig(capture_enabled=path is None))
    before = len(list(backend.transcript_store.list_distill_jobs()))
    result = tool_handlers.tool_prepare_session_distill(
        client="codex", session_id="correction", target_knowledge=[old], run_ingest=run_ingest,
    )
    assert result["success"] is False, result
    assert len(list(backend.transcript_store.list_distill_jobs())) == before
    assert tool_handlers.tool_search_memory(query="")["memories"][0]["statement"] == old["statement"]


def test_explicit_wrong_owner_fails_before_source_preparation(device):
    backend, write = device
    write("original", "For future work, retain the explicit unknown author naming state.")
    packet = tool_handlers.tool_prepare_session_distill(client="codex", scope="all", session_id="original")
    remember(backend, packet, "Author naming is explicitly undecided.")
    old = tool_handlers.tool_search_memory(query="")["memories"][0]
    before = len(list(backend.transcript_store.list_distill_jobs()))
    write("correction", "Use full author names now.")
    result = tool_handlers.tool_prepare_session_distill(
        client="codex", session_id="correction", project_name="other", target_knowledge=[old],
    )
    assert result["success"] is False and "does not match" in result["error"]
    assert len(list(backend.transcript_store.list_distill_jobs())) == before
    raw = tool_handlers.tool_search_raw(pattern="Author", project_name="other")
    assert raw["current_knowledge"] == []
    assert "undecided" in json.dumps(tool_handlers.tool_search_memory(query=""))


def test_same_captured_native_source_reuses_resolved_owner_when_original_is_unavailable(device):
    backend, write = device
    path = write("shared-native", "For future club use, preserve all named conditions.")
    prepare_correction_source(backend, project_name="global", client="codex", session_id="shared-native")
    owned = prepare_correction_source(backend, project_name="club", client="codex", session_id="shared-native")
    retained = path.with_suffix(".retained")
    path.rename(retained)
    assert retained.is_file()
    reused = prepare_correction_source(
        backend, project_name="club", client="codex", session_id="shared-native", run_ingest=False,
    )
    assert reused.id == owned.id


def test_raw_context_reopens_repository_in_its_registered_root_and_keeps_changes_visible(device, tmp_path):
    from hashlib import sha256
    from harness_mem.core.schemas import (
        AssimilationDecision, KnowledgeCandidate, KnowledgeEntry, ProjectKnowledgeSourceRef,
    )
    from harness_mem.core.schemas.project_profile import ProjectProfile
    from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

    backend, _ = device
    root = tmp_path / "project"
    root.mkdir()
    source = root / "RULE.md"
    source.write_text("RepositoryMarker uses five days.", encoding="utf-8")
    profile = ProjectProfile(project_name="club", project_root=str(root))
    profiles = LocalProjectProfileStore(backend.data_dir)
    asyncio.run(profiles.save(profile))
    entry = KnowledgeEntry(project_name="club", title="Loan policy", statement="RepositoryMarker uses five days.", module_path=["Loans"])
    candidate = KnowledgeCandidate(project_name="club", candidate_type="memory", statement=entry.statement)
    decision = AssimilationDecision(
        project_name="club", candidate_id=candidate.id, disposition="add",
        canonical_truth_ids=[entry.id], reason="Isolated repository fixture.",
    )
    asyncio.run(backend.structured_store.knowledge_store.apply_current_change(
        candidate_before=candidate, candidate_after=candidate.model_copy(update={"status": "assimilated"}),
        decision=decision, added_entries=[entry], predecessor_entries=[],
        source_refs_by_entry={entry.id: [ProjectKnowledgeSourceRef(
            kind="repository", label="RULE.md", target=source.as_uri(),
            digest=sha256(source.read_bytes()).hexdigest(),
        )]},
    ))
    result = tool_handlers.tool_search_raw(pattern="RepositoryMarker", project_name="club")
    assert result["current_knowledge"][0]["source_status"] == "verified"
    assert result["current_knowledge"][0]["source_evidence"][0]["content"] == source.read_text()
    source.write_text("RepositoryMarker now uses seven days.", encoding="utf-8")
    result = tool_handlers.tool_search_raw(pattern="RepositoryMarker", project_name="club")
    assert result["current_knowledge"][0]["source_status"] == "contradicted"
    assert result["current_knowledge"][0]["statement"] == entry.statement
    outside = tmp_path / "different-root"
    outside.mkdir()
    asyncio.run(profiles.save(profile.model_copy(update={"project_root": str(outside)})))
    result = tool_handlers.tool_search_raw(pattern="RepositoryMarker", project_name="club")
    assert result["current_knowledge"][0]["source_status"] == "unverified"
    assert result["current_knowledge"][0]["source_evidence"][0]["content"] is None
