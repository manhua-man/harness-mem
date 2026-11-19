"""No-model wrapper contracts using disposable, self-contained fixtures.

The two native upstream integration tests require HARNESS_MEM_TEST_UPSTREAM_ROOT
to name an existing read-only mirror. All generated fixtures use pytest's
external basetemp. They never download an upstream.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "code" / "scripts" / "matched_memory_host.py"
spec = importlib.util.spec_from_file_location("matched_memory_host_test", SCRIPT)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


@pytest.fixture
def experiment(tmp_path):
    temp_root = tmp_path.resolve()
    run = temp_root / "run"
    run.mkdir()
    project = run / "project"
    project.mkdir()
    upstream = temp_root / "upstream-source"
    upstream.mkdir()  # Scope/HM contracts do not execute upstream code.
    (project / ".harness-mem.toml").write_text("[distill.autonomous]\nenabled = false\n", encoding="utf-8")
    sid = str(uuid4())
    source = run / "native-codex" / "sessions" / "2026" / "10" / "07" / f"rollout-2026-10-07-{sid}.jsonl"
    source.parent.mkdir(parents=True)
    records = [
        {"type": "session_meta", "payload": {"id": sid, "cwd": str(project), "timestamp": "2026-10-07T00:00:00Z"}},
        {"type": "response_item", "payload": {"type": "message", "turn_id": "fixture-turn", "role": "user", "content": [
            {"type": "input_text", "text": "For this fixture retain original transcripts."}]}},
        {"type": "response_item", "payload": {"type": "message", "turn_id": "fixture-turn", "phase": "final_answer", "role": "assistant", "content": [
            {"type": "output_text", "text": "Original transcripts are retained in this fixture."}]}},
    ]
    source.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
    payload = {
        "schema_version": 2, "artifact_root": str(temp_root),
        "run_root": str(run), "project_root": str(project),
        "project_name": "project", "native_root": str(run / "native-codex"),
        "data_dir": str(run / "isolateddata"), "notes_dir": str(run / "isolatednotes"),
        "audit_path": str(run / "audit" / "calls.ndjson"), "upstream_root": str(upstream),
        "upstream_distill": str(run / "upstream-distill"), "kb_file": str(run / "kb.md"),
        "session_ids": [sid],
    }
    manifest_path = run / "manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    yield payload, manifest_path, source
    assert host.within(run.resolve(), temp_root.resolve()) and run != temp_root


@pytest.fixture
def native_upstream_experiment(experiment):
    configured = os.environ.get("HARNESS_MEM_TEST_UPSTREAM_ROOT")
    if not configured:
        pytest.skip("native upstream integration requires HARNESS_MEM_TEST_UPSTREAM_ROOT")
    rewrite(experiment, upstream_root=configured)
    manifest = host.Manifest(experiment[1])
    adapter = (manifest.paths["upstream_root"] / "adapters" /
               "codex-session-distill" / "bin" / "session-distill.py")
    assert adapter.is_file(), "configured upstream clone is missing its native adapter"
    return experiment


def invoke(experiment, mode="search-probe", args=()):
    _, path, _ = experiment
    return subprocess.run([sys.executable, "-B", str(SCRIPT), "--mode", mode,
                           "--manifest", str(path), *args],
                          text=True, encoding="utf-8", capture_output=True, timeout=45)


def rewrite(experiment, **changes):
    payload, path, _ = experiment
    payload.update(changes)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_external_scope_rejects_repository_ancestor_and_read_only_source_overlap(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for root in (repo, tmp_path):
        with pytest.raises(host.ScopeError, match="outside and disjoint"):
            host.validate_external_scope(root, root / "run", root / "source", repo=repo)
    root = tmp_path / "artifacts"
    root.mkdir()
    with pytest.raises(host.ScopeError, match="overlaps"):
        host.validate_external_scope(root, root / "run", root / "run/source", repo=repo)
    with pytest.raises(host.ScopeError, match="task-owned"):
        host.validate_external_scope(root, root / "run", tmp_path / "unapproved-source", repo=repo)


def test_external_manifest_cannot_be_loaded_from_outside_its_run(experiment):
    payload, path, _ = experiment
    outside = Path(payload["artifact_root"]) / "outside-manifest.json"
    outside.write_bytes(path.read_bytes())
    with pytest.raises(host.ScopeError, match="manifest must be below"):
        host.Manifest(outside)


@pytest.mark.parametrize("field", ["run_root", "project_root", "native_root", "data_dir",
                                  "notes_dir", "audit_path", "upstream_root", "upstream_distill", "kb_file"])
def test_manifest_rejects_escape(experiment, field):
    rewrite(experiment, **{field: str(REPO / "outside-experiment")})
    with pytest.raises(host.ScopeError):
        host.Manifest(experiment[1])


def test_scope_contracts_need_no_upstream_source(experiment):
    manifest = host.Manifest(experiment[1])
    assert list(manifest.paths["upstream_root"].iterdir()) == []
    assert host.upstream_command(manifest, ["index"]) == ("index", [])


@pytest.mark.parametrize("context", ["rootless", "missing"])
def test_isolated_device_host_lists_and_prepares_without_a_source_directory(experiment, context, monkeypatch):
    payload, _, source = experiment
    records = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    records[0]["payload"].pop("cwd")
    if context == "missing":
        records[0]["payload"]["cwd"] = str(Path(payload["run_root"]) / "former-workspace")
    source.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    original = source.read_bytes()
    rewrite(experiment, device_scope=True, project_name="global")
    from harness_mem.distill import Distill
    workflow = Distill(payload["data_dir"])
    monkeypatch.setenv("CODEX_HOME", payload["native_root"])
    inventory = workflow.sessions(clients=["codex"])
    assert inventory["scope"] == "all" and len(inventory["sessions"]) == 1, inventory
    packet = workflow.prepare(sessions=inventory["sessions"], evidence_mode="semantic")
    assert packet["success"] and packet["session_id"] == payload["session_ids"][0], packet
    assert not (Path(payload["data_dir"]) / "profiles").exists()
    assert source.read_bytes() == original


def test_manifest_rejects_missing_upstream_directory(experiment):
    payload, path, _ = experiment
    rewrite(experiment, upstream_root=str(Path(payload["artifact_root"]) / "missing-upstream"))
    with pytest.raises(host.ScopeError, match="upstream_root must exist"):
        host.Manifest(path)


def test_manifest_requires_disabled_background_and_absolute_paths(experiment):
    payload, path, _ = experiment
    rewrite(experiment, data_dir="relative")
    with pytest.raises(host.ScopeError, match="absolute"):
        host.Manifest(path)
    rewrite(experiment, data_dir=str(Path(payload["run_root"]) / "isolateddata"))
    (Path(payload["project_root"]) / ".harness-mem.toml").write_text(
        "[distill.autonomous]\nenabled=true\n", encoding="utf-8")
    with pytest.raises(host.ScopeError, match="enabled=false"):
        host.Manifest(path)


def test_search_probe_uses_scope_from_manifest_for_every_question(experiment):
    payload, _, _ = experiment
    case = {"caseId": "fixture", "query": "original transcripts",
            "scope": "all", "data_dir": str(REPO), "project_name": "other"}
    (Path(payload["run_root"]) / "adapter-input.json").write_text(
        json.dumps({"cases": [case]}), encoding="utf-8")
    result = invoke(experiment)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(rows) == 31
    for row in rows:
        assert row["caseId"] == case["caseId"]
        response = row["response"]
        assert response["status"] == "empty"
        assert response["project_name"] == payload["project_name"]
        assert response["query"] == case["query"]
        assert response["retry_without_project_filter"]["arguments"]["scope"] == "all"


def test_unknown_native_fixture_is_rejected_before_scan(experiment):
    _, path, source = experiment
    unknown = source.with_name(f"rollout-{uuid4()}.jsonl")
    unknown.write_bytes(source.read_bytes())
    with pytest.raises(host.ScopeError, match="unknown session"):
        host.Manifest(path)


def test_symlink_escape_rejected(experiment):
    payload, path, _ = experiment
    link = Path(payload["run_root"]) / "outside"
    try:
        link.symlink_to(REPO, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this Windows account")
    with pytest.raises(host.ScopeError, match="linked path"):
        host.Manifest(path)


@pytest.mark.parametrize("args", [
    ["prune"], ["prune-raw"], ["sync"], ["install"], ["run"], ["bundle", "--force"],
    ["run", "00000000-0000-0000-0000-000000000000"],
    ["mark", "00000000-0000-0000-0000-000000000000", "distilled"],
    ["deep", "--force-bundle"], ["deep", "--batch-size", "3"],
])
def test_upstream_dangerous_and_unknown_commands_rejected(experiment, args):
    with pytest.raises(host.ScopeError) as rejection:
        host.upstream_command(host.Manifest(experiment[1]), args)
    result = invoke(experiment, mode="upstream", args=args)
    assert result.returncode == 2 and str(rejection.value) in result.stderr
    assert not Path(experiment[0]["upstream_distill"]).exists()


def test_upstream_native_prepare_deep_close_preserves_evidence_and_sources(native_upstream_experiment):
    experiment = native_upstream_experiment
    payload, _, source = experiment
    original = source.read_bytes()
    sid = payload["session_ids"][0]
    for args in (["index"], ["bundle", sid], ["deep", "--session-ids", sid]):
        result = invoke(experiment, mode="upstream", args=args)
        assert result.returncode == 0, result.stderr
    distill = Path(payload["upstream_distill"])
    assert Path(payload["kb_file"]).is_file()
    assert not (distill / "knowledge-base.md").exists()
    answers = distill / "distilled" / "answer-packets" / f"{sid}.md"
    assert answers.is_file() and "PENDING" in answers.read_text(encoding="utf-8")
    revision = distill / "revisions" / sid
    assert revision.is_dir()
    notes = Path(payload["notes_dir"])
    notes.mkdir(exist_ok=True)
    (notes / f"{sid}.md").write_text(
        "# Note\n\n## Final Session Review\n"
        "- **Final user request:** fixture request\n- **Final outcome:** completed\n"
        "- **Last turn state:** completed\n- **Contradictions:** none\n- **Open items:** none\n"
        "- **Evidence status:** all ANSWERED\n- **Promotion allowed:** yes\n\n"
        "## Promotion Decision\nNo Promotion. raw transcript reviewed.\n", encoding="utf-8")
    result = invoke(experiment, mode="upstream", args=["mark", sid, "distilled"])
    assert result.returncode == 0, result.stderr + result.stdout
    snapshot = Path(payload["run_root"]) / "audit-before-close" / sid
    saved = json.loads((snapshot / "snapshot.json").read_text(encoding="utf-8"))
    assert saved["missing"] == []
    assert (snapshot / "answer-packet.md").is_file() and (snapshot / "revision").is_dir()
    assert (snapshot / "note.md").read_bytes() == (notes / f"{sid}.md").read_bytes()
    assert (snapshot / "knowledge-base.md").read_bytes() == Path(payload["kb_file"]).read_bytes()
    assert not answers.exists() and not revision.exists()
    assert not (distill / "packets" / f"{sid}.md").exists()
    assert source.read_bytes() == original


def test_upstream_rejects_poisoned_persisted_path(native_upstream_experiment):
    experiment = native_upstream_experiment
    payload, _, _ = experiment
    result = invoke(experiment, mode="upstream", args=["index"])
    assert result.returncode == 0, result.stderr
    state_path = Path(payload["upstream_distill"]) / "manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["sessions"][0]["file_path"] = str(REPO / "AGENTS.md")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    result = invoke(experiment, mode="upstream", args=["bundle", payload["session_ids"][0]])
    assert result.returncode == 2 and "escapes" in result.stderr
    assert not list((Path(payload["upstream_distill"]) / "packets").glob("*.md"))

def test_agent_source_read_is_bounded_and_prepare_uses_isolated_data(experiment, monkeypatch):
    from harness_mem.distill import Distill
    from harness_mem.storage.canonical_store import canonical_store_path

    payload, _, source = experiment
    data = Path(payload["data_dir"])
    monkeypatch.setenv("CODEX_HOME", payload["native_root"])
    workflow = Distill(data)
    inventory = workflow.sessions(project_root=payload["project_root"], clients=["codex"])
    selected, = inventory["sessions"]
    assert selected["session_id"] == payload["session_ids"][0]
    page = workflow.source(selected, project_root=payload["project_root"])
    first = workflow.source(selected, project_root=payload["project_root"], page_chars=32)
    second = workflow.source(selected, project_root=payload["project_root"], offset=first["next_offset"], page_chars=32)
    assert first["content_sha256"] == second["content_sha256"] == page["content_sha256"]
    assert first["content"] + second["content"] == page["content"][:64]
    assert "Original transcripts are retained in this fixture." in page["content"]
    assert page["complete"] and page["next_offset"] is None
    assert not canonical_store_path(data).exists()
    assert not (data / "transcript_ledger.sqlite").exists()
    packet = workflow.prepare(sessions=[selected], project_root=payload["project_root"])
    assert packet["success"], packet
    assert (data / "transcript_ledger.sqlite").is_file()
    assert source.exists()
