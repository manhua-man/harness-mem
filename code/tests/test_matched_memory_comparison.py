"""Synthetic, no-model contracts for collection, isolation and measurement."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_matched_memory_comparison.py"
spec = importlib.util.spec_from_file_location("matched_comparison", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_role_conversion_keeps_middle_and_tail_and_original_bytes():
    baseline = mod.load_baseline()
    source = next(row for row in baseline["sources"] if row["id"] == "F5")
    messages = mod.source_messages(source["text"])
    combined = "\n".join(body for _, body in messages)
    assert "F5-MIDDLE-ERROR" in combined
    assert "Security review remains unfinished." in combined
    assert len(messages) == 120
    rows = mod.native_records(source, Path("/fictional/lantern"), "fixed-id", 0)
    assert sum(row["type"] == "response_item" for row in rows) == 120
    assert sum(row["type"] == "turn_context" for row in rows) == 60


def test_unheaded_project_preamble_is_not_discarded():
    baseline = mod.load_baseline()
    source = next(row for row in baseline["sources"] if row["id"] == "F10")
    assert mod.source_messages(source["text"])[0][1].startswith("Fictional project Lantern.")


def test_command_preserves_model_provider_but_disables_ambient_tools(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"project_root": str(tmp_path / "lantern")}), encoding="utf-8")
    monkeypatch.setattr(mod.shutil, "which", lambda _: "codex")
    config = {"model": "configured-model", "model_provider": "configured-provider",
              "ambient_mcp_names": ["mcp_router", "cua_repl"]}
    for product in ("harness-mem", "session-distill-skills"):
        command = mod.command_for(product, manifest, config, tmp_path / "reply.txt")
        joined = " ".join(command)
        assert "--ephemeral" in command
        assert "features.memories=false" in command
        assert 'mcp_servers.mcp_router.enabled=false' in command
        assert 'mcp_servers."' not in joined
        assert "model=" not in joined and "model_provider=" not in joined
        assert ("mcp_servers.matched_hm.command=" in joined) == (product == "harness-mem")
        assert ('mcp_servers.matched_hm.default_tools_approval_mode="approve"' in command) == (product == "harness-mem")
        assert not any(item.startswith("approval_policy=") for item in command)
        assert not any(item.startswith("apps.") for item in command)


def test_cli_dotted_override_refuses_unrepresentable_names(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"project_root": str(tmp_path)}), encoding="utf-8")
    monkeypatch.setattr(mod.shutil, "which", lambda _: "codex")
    with pytest.raises(ValueError, match="dotted override"):
        mod.command_for("harness-mem", path, {"ambient_mcp_names": ["private server"]}, tmp_path / "out")


def test_static_config_check_no_exec_or_private_transport_export(monkeypatch):
    commands = []
    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps([
            {"name": "ambient", "enabled": False, "transport": {"url": "private", "headers": "secret"}},
            {"name": "matched_hm", "enabled": True, "transport": {"command": "python"}},
        ]), "")
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    report = mod.check_cli_configuration(["node", "codex.js", "exec", "--json", "-c",
                                         "mcp_servers.matched_hm.enabled=true", "-"])
    assert commands == [["node", "codex.js", "-c", "mcp_servers.matched_hm.enabled=true", "mcp", "list", "--json"]]
    assert report["model_calls"] == 0 and report["status"] == "passed"
    assert "secret" not in json.dumps(report) and "private" not in json.dumps(report)


@pytest.mark.parametrize("servers", [
    [{"name": "ambient", "enabled": True}, {"name": "matched_hm", "enabled": True}],
    [{"name": "matched_hm", "enabled": False}],
])
def test_static_config_check_stops_on_incorrect_enabled_scope(monkeypatch, servers):
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, json.dumps(servers), ""))
    report = mod.check_cli_configuration(["codex", "exec", "-c", "mcp_servers.matched_hm.enabled=true", "-"])
    assert report["status"] == "failed" and report["model_calls"] == 0


def test_missing_notes_or_unfinished_jobs_stop_collection_without_semantic_pass():
    manifest = {"session_ids": ["session"]}
    snapshot = {"source_retention_verified": True, "jobs": [{"session_id": "session", "status": "completed"}],
                "notes": []}
    assert mod.minimum_artifact_gate("harness-mem", snapshot, manifest) is False
    snapshot["notes"] = [{"path": "/fictional/session.md", "text": "A real nonempty note"}]
    assert mod.minimum_artifact_gate("harness-mem", snapshot, manifest) is True
    snapshot["jobs"][0]["status"] = "queued"
    assert mod.minimum_artifact_gate("harness-mem", snapshot, manifest) is False
    assert mod.minimum_artifact_gate("session-distill-skills", snapshot, manifest) is False


def test_prepare_refuses_outside_scope_or_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    with pytest.raises(ValueError, match="under repository"):
        mod.prepare_experiment(tmp_path / "upstream", tmp_path / "run")
    upstream = tmp_path / ".tmp/upstream"
    upstream.mkdir(parents=True)
    run = tmp_path / ".tmp/run"
    run.mkdir()
    with pytest.raises(ValueError, match="overwrite"):
        mod.prepare_experiment(upstream, run)


def test_prepare_same_complete_sources_and_initial_truth_without_oracle(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    upstream = tmp_path / ".tmp/upstream"
    upstream.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(upstream)], check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "--quiet", "--allow-empty", "-m", "fictional upstream"], cwd=upstream, check=True)
    run = tmp_path / ".tmp/run"
    result = mod.prepare_experiment(upstream, run)
    left, right = result["arms"].values()
    assert left["session_ids"] == right["session_ids"] and len(left["session_ids"]) == 7
    assert [row["text_sha256"] for row in left["sources"]] == [row["text_sha256"] for row in right["sources"]]
    assert Path(left["native_root"]).parent != Path(left["project_root"])
    assert not list(Path(left["project_root"]).rglob("*baseline*"))
    assert (run / "evaluator/frozen-baseline.json").is_file()
    snapshot = asyncio.run(mod.collect_hm(left))
    assert len(snapshot["knowledge"]) == 3
    assert all(row["sources"] for row in snapshot["knowledge"])
    assert mod.collect_product("harness-mem", left)["source_retention_verified"] is True


def test_prompts_no_oracle_and_explicit_real_product_work(tmp_path):
    path = tmp_path / "manifest.json"
    manifest = {"project_root": str(tmp_path / "lantern"), "project_name": "lantern",
                "native_root": str(tmp_path / "native"), "session_ids": ["fictional-session"],
                "sources": [{"session_id": "fictional-session", "text_path": str(tmp_path / "raw.txt")}],
                "kb_file": str(tmp_path / "kb.md"), "notes_dir": str(tmp_path / "notes"),
                "upstream_distill": str(tmp_path / "distill")}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    for product in ("harness-mem", "session-distill-skills"):
        prompt = mod.workflow_prompt(product, path, preflight=False)
        assert "quality_baseline.json" not in prompt
        assert "Distillation performance preference" not in prompt
        assert "逐点验证" in prompt and "实际完成" in prompt
        assert "全部1场" in prompt
        assert "初始知识" in prompt and "完整内容" in prompt
        if product == "harness-mem":
            assert "product-instructions" in prompt and "hm.md" in prompt
            assert mod.daily_reply_instructions() in prompt
            assert "直接展示实际保存的标题和正文" in prompt
            assert "未完成事项单独说" in prompt
            assert "保留已保存的成果" in prompt
        if product == "session-distill-skills":
            assert "只是待验证材料" in prompt
            preflight = mod.workflow_prompt(product, path, preflight=True)
            assert preflight.index(" index;") < preflight.index(" bundle ")


def test_reply_instructions_use_only_the_canonical_result_section(tmp_path, monkeypatch):
    entry = tmp_path / "code/plugins/harness-mem/commands/hm/hm.md"
    entry.parent.mkdir(parents=True)
    entry.write_text("## Earlier\nNot a reply rule.\n\n## 结果与失败\n\n"
                     "Show saved knowledge and unfinished work.\n\n## Later\nNot a reply rule.\n",
                     encoding="utf-8")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    assert mod.daily_reply_instructions() == (
        "## 结果与失败\n\nShow saved knowledge and unfinished work."
    )


@pytest.mark.parametrize("text", ["## Other\nNo rules.", "## 结果与失败\n\n## Later\nNot rules."])
def test_reply_instructions_reject_missing_or_empty_canonical_section(tmp_path, monkeypatch, text):
    entry = tmp_path / "code/plugins/harness-mem/commands/hm/hm.md"
    entry.parent.mkdir(parents=True)
    entry.write_text(text, encoding="utf-8")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    with pytest.raises(ValueError, match="reply instructions are missing"):
        mod.daily_reply_instructions()


@pytest.mark.parametrize("product", ["harness-mem", "session-distill-skills"])
def test_preflight_rejects_failure_containing_success_word(tmp_path, product):
    assert mod.preflight_verified("Not PREFLIGHT_OK: failed", product, tmp_path / "absent.json") is False


@pytest.mark.parametrize("result", [{"success": False}, {"success": False, "error": "unsupported evidence kind"}])
def test_completed_mcp_transport_does_not_hide_a_rejected_product_operation(result):
    event = {"type": "item.completed", "item": {
        "type": "mcp_tool_call", "status": "completed", "error": None,
        "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
    }}
    assert mod.failed_mcp_results([event]) == [event["item"]]


@pytest.mark.parametrize("product", ["harness-mem", "session-distill-skills"])
def test_preflight_exact_word_without_native_evidence_is_not_success(tmp_path, product):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"audit_path": str(tmp_path / "absent"),
                                "upstream_distill": str(tmp_path / "distill")}), encoding="utf-8")
    assert mod.preflight_verified("PREFLIGHT_OK", product, path) is False


def test_hm_preflight_requires_successful_complete_readable_inventory(tmp_path):
    path, audit = tmp_path / "manifest.json", tmp_path / "audit.jsonl"
    manifest = {"project_root": str(tmp_path), "audit_path": str(audit), "session_ids": ["s1", "s2"]}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    events = write_instruction_events(tmp_path, manifest)
    def write_inventory(rows):
        result = {"content": [{"type": "text", "text": json.dumps({"success": True, "sessions": rows})}]}
        audit.write_text(json.dumps({"params": {"name": "inspect_sessions"}, "response": {"result": result}}), encoding="utf-8")
        write_instruction_events(tmp_path, manifest)
        with events.open("a", encoding="utf-8") as output:
            output.write("\n" + json.dumps({"type": "item.completed", "item": {
                "type": "mcp_tool_call", "server": "matched_hm", "tool": "inspect_sessions",
                "status": "completed", "arguments": {"project_root": str(tmp_path)}, "result": result,
            }}))
    write_inventory([{"session_id": "s1", "readability": "readable"}])
    assert not mod.preflight_verified("PREFLIGHT_OK", "harness-mem", path)
    write_inventory([{"session_id": "s1", "readability": "readable"}, {"session_id": "s2", "readability": "unreadable"}])
    assert not mod.preflight_verified("PREFLIGHT_OK", "harness-mem", path)
    write_inventory([{"session_id": sid, "readability": "readable"} for sid in ("s1", "s2")])
    assert mod.preflight_verified("PREFLIGHT_OK", "harness-mem", path)
    write_instruction_events(tmp_path, manifest)
    assert not mod.preflight_verified("PREFLIGHT_OK", "harness-mem", path)
    events.unlink()
    assert not mod.preflight_verified("PREFLIGHT_OK", "harness-mem", path)


def write_instruction_events(root, manifest, *, status="completed", exit_code=0, truncate=False):
    references = root / "product-instructions/references"
    references.mkdir(parents=True, exist_ok=True)
    (references / "distillation-rules.md").write_text("Full fictional rules\nLast required rule.", encoding="utf-8")
    files = mod.instruction_files("harness-mem", manifest)
    for path in files:
        if not path.exists():
            path.write_text(f"Full fictional {path.name}\nLast required paragraph.", encoding="utf-8")
    events = root / "preflight.events.jsonl"
    rows = [{"type": "item.completed", "item": {
        "type": "command_execution", "status": status, "exit_code": exit_code,
        "aggregated_output": path.read_text(encoding="utf-8")[:8] if truncate else path.read_text(encoding="utf-8"),
    }} for path in files]
    events.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return events


@pytest.mark.parametrize("status,exit_code,truncate", [
    ("failed", -1, False), ("completed", 1, False), ("in_progress", 0, False),
    ("completed", 0, True),
])
def test_instruction_proof_rejects_failed_incomplete_or_truncated_reads(tmp_path, status, exit_code, truncate):
    manifest = {"project_root": str(tmp_path)}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    events = write_instruction_events(tmp_path, manifest, status=status, exit_code=exit_code, truncate=truncate)
    assert not mod.instruction_reads_verified("harness-mem", path, events)


def test_instruction_proof_requires_canonical_entry_references_and_initial_knowledge(tmp_path):
    manifest = {"project_root": str(tmp_path)}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    events = write_instruction_events(tmp_path, manifest)
    assert mod.instruction_reads_verified("harness-mem", path, events)
    rows = events.read_text(encoding="utf-8").splitlines()
    for index in range(len(rows)):
        events.write_text("\n".join(rows[:index] + rows[index + 1:]), encoding="utf-8")
        assert not mod.instruction_reads_verified("harness-mem", path, events)
    events.write_text("\n".join(rows), encoding="utf-8")
    (tmp_path / "product-instructions/hm.md").unlink()
    assert not mod.instruction_reads_verified("harness-mem", path, events)


def test_native_terminal_failure_is_not_workflow_success_even_when_cli_exits_zero(tmp_path, monkeypatch):
    manifest = {"project_root": str(tmp_path)}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(mod, "workflow_prompt", lambda *_args, **_kwargs: "fictional prompt")
    monkeypatch.setattr(mod, "command_for", lambda *_args: ["fictional-cli"])
    monkeypatch.setattr(mod, "check_cli_configuration", lambda _cmd: {"status": "passed"})
    class FailedTerminal:
        returncode = 0
        def __init__(self, _command, **kwargs):
            self.log = kwargs["stdout"]
        def communicate(self, _prompt, **_kwargs):
            rows = [{"type": "item.completed", "item": {
                "type": "command_execution", "status": "failed", "exit_code": -1,
                "aggregated_output": "Terminal setup failed",
            }}, {"type": "turn.completed", "usage": {}}]
            self.log.write("\n".join(json.dumps(row) for row in rows).encode())
            (tmp_path / "workflow.reply.txt").write_text("本次尚未开始，记忆没有改动。", encoding="utf-8")
    monkeypatch.setattr(mod.subprocess, "Popen", FailedTerminal)
    result = mod.run_cli("harness-mem", path, {}, preflight=False, timeout_seconds=10)
    assert result["status"] == "failed" and result["return_code"] == 0
    assert result["failed_terminal_calls"] == 1 and not result["instruction_reads_verified"]
    assert result["product_completion_verified"] is False


def test_drift_after_workflow_prevents_starting_another_product(tmp_path, monkeypatch):
    run = tmp_path / "run"
    arms = {}
    for product in ("harness-mem", "session-distill-skills"):
        project = run / product / "lantern"
        project.mkdir(parents=True)
        for name in ("AGENTS.md", ".harness-mem.toml", "initial-knowledge.md"):
            (project / name).write_text("fictional frozen input", encoding="utf-8")
        manifest = {"project_root": str(project), "sources": [], "runtime_fingerprint": "before",
                    "upstream_root": str(tmp_path / "upstream"), "upstream_tree_sha256": mod.upstream_source_fingerprint(tmp_path / "upstream")}
        (project.parent / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        arms[product] = manifest
    experiment = {"arms": arms}
    monkeypatch.setattr(mod, "prepare_experiment", lambda *_: experiment)
    monkeypatch.setattr(mod, "safe_configuration", lambda: {"fixture": True})
    monkeypatch.setattr(mod, "install_instructions", lambda product, manifest: (Path(manifest["project_root"]) / "product-instructions").mkdir())
    current = ["before"]
    monkeypatch.setattr(mod, "autonomous_runtime_fingerprint", lambda: current[0])
    calls = []
    def fake_call(product, path, config, *, preflight, timeout_seconds):
        calls.append((product, preflight))
        if not preflight:
            current[0] = "after"
        return {"status": "passed"}
    monkeypatch.setattr(mod, "run_cli", fake_call)
    monkeypatch.setattr(mod.sys, "argv", ["collector", "--upstream", str(tmp_path), "--run", str(run)])
    with pytest.raises(ValueError, match="runtime drift"):
        mod.main()
    assert calls == [("harness-mem", True), ("harness-mem", False)]


def test_failed_native_preflight_stops_before_workflow_or_upstream(tmp_path, monkeypatch):
    run = tmp_path / "run"
    arms = {}
    for product in ("harness-mem", "session-distill-skills"):
        project = run / product / "lantern"
        project.mkdir(parents=True)
        for name in ("AGENTS.md", ".harness-mem.toml", "initial-knowledge.md"):
            (project / name).write_text("fictional frozen input", encoding="utf-8")
        manifest = {"project_root": str(project), "sources": []}
        (project.parent / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        arms[product] = manifest
    monkeypatch.setattr(mod, "prepare_experiment", lambda *_: {"arms": arms})
    monkeypatch.setattr(mod, "safe_configuration", lambda: {"fixture": True})
    monkeypatch.setattr(mod, "assert_frozen_experiment", lambda _: None)
    monkeypatch.setattr(mod, "install_instructions", lambda product, manifest: (Path(manifest["project_root"]) / "product-instructions").mkdir())
    calls = []
    def failed_preflight(product, path, config, *, preflight, timeout_seconds):
        calls.append((product, preflight))
        return {"status": "failed", "return_code": 0, "reason": "tool approval denied"}
    monkeypatch.setattr(mod, "run_cli", failed_preflight)
    monkeypatch.setattr(mod.sys, "argv", ["collector", "--upstream", str(tmp_path), "--run", str(run)])
    assert mod.main() == 2
    assert calls == [("harness-mem", True)]
    result = json.loads((run / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "blocked" and result["real_quality_comparison"] is False


def test_upstream_source_drift_is_detected_before_another_invocation(tmp_path, monkeypatch):
    source = tmp_path / "upstream/adapter.py"
    source.parent.mkdir()
    source.write_text("fictional original implementation", encoding="utf-8")
    monkeypatch.setattr(mod, "safe_configuration", lambda: {"fixture": True})
    monkeypatch.setattr(mod, "autonomous_runtime_fingerprint", lambda: "frozen")
    experiment = {"runner_sha256": mod.digest(SCRIPT),
                  "host_sha256": mod.digest(mod.REPO_ROOT / "code/scripts/matched_memory_host.py"),
                  "configuration": {"fixture": True}, "input_hashes": {},
                  "arms": {"upstream": {"upstream_root": str(source.parent),
                                        "upstream_tree_sha256": mod.upstream_source_fingerprint(source.parent),
                                        "runtime_fingerprint": "frozen"}}}
    mod.assert_frozen_experiment(experiment)
    source.write_text("fictional modified implementation", encoding="utf-8")
    with pytest.raises(ValueError, match="upstream source drift"):
        mod.assert_frozen_experiment(experiment)


@pytest.mark.parametrize("name", ["manifest.json", "SKILL.md", "initial-knowledge.md", "source.jsonl"])
def test_other_frozen_input_changes_stop_before_another_invocation(tmp_path, monkeypatch, name):
    source = tmp_path / name
    source.write_text("fictional original input", encoding="utf-8")
    monkeypatch.setattr(mod, "safe_configuration", lambda: {"fixture": True})
    experiment = {"runner_sha256": mod.digest(SCRIPT),
                  "host_sha256": mod.digest(mod.REPO_ROOT / "code/scripts/matched_memory_host.py"),
                  "configuration": {"fixture": True}, "input_hashes": {str(source): mod.digest(source)},
                  "arms": {}}
    mod.assert_frozen_experiment(experiment)
    source.write_text("fictional modified input", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen input drift"):
        mod.assert_frozen_experiment(experiment)
