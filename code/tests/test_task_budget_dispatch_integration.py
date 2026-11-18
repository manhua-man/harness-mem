"""Real decide/verify/assimilate and public manual writes through the Stage 6 gate.

Transports are in-process doubles. Production host names never receive a fake
cap, and the patched Popen / Codex app-server seams must not run.
"""

from __future__ import annotations

import json
import os
import runpy
import time
from pathlib import Path

import pytest

os.environ["HARNESS_MEM_DISABLE_EMBEDDINGS"] = "1"

from harness_mem.autonomous.executors.codex_app_server import CodexAppServer
from harness_mem.autonomous.executors.host_structured_cli import HostStructuredCliProvider
from harness_mem.autonomous.executors.task_budget import (
    NativeDispatchRequest,
    NativeDispatchResult,
    TaskBudgetRefusal,
    bind_maintenance_task,
    fake_input_capability,
    fake_output_limit_surface,
    maintenance_task_scope,
    read_task_budget_receipt,
    task_budget_coverage,
    task_budget_receipt_path,
)
from harness_mem.autonomous.models import (
    AgentExtractionDecision,
    AssimilationDecision,
    CandidateVerificationDecision,
)
from harness_mem.autonomous.provider import ProviderError
from harness_mem.commands.config_cmds import cmd_config_list, cmd_config_set
from harness_mem.commands.separated_assimilation import target_version
from harness_mem.config.errors import ConfigValidationError
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.config.writer import set_value
from harness_mem.qualification.distill_acceptance import run_model_samples

_HELPERS = runpy.run_path(str(Path(__file__).with_name("test_manual_session_flow.py")))
manual_fixture = _HELPERS["manual_fixture"]
_PRODUCTION_HOSTS = ("codex", "claude-code", "hermes", "opencode", "antigravity")


def _budget_config(**overrides: object) -> MergedConfig:
    values: dict[str, object] = {
        "task_model_budget_max_calls": 4,
        "task_model_budget_max_seconds": 1000,
        "task_model_budget_max_input_tokens": 10000,
        "task_model_budget_max_output_tokens": 4000,
        "task_model_budget_host_max_output_tokens": 50,
    }
    values.update(overrides)
    return MergedConfig(**values)  # type: ignore[arg-type]


def _empty_review() -> AgentExtractionDecision:
    return AgentExtractionDecision.model_validate({
        "review": {
            "summary": "The isolated call carried no durable project fact.",
            "final_request": "Record nothing.",
            "actual_result": "Nothing was recorded.",
            "no_candidate_reason": "This isolated call has no durable project fact.",
        },
        "points": [],
    })


def _decide_manifest() -> dict[str, object]:
    return {
        "zero_candidate_challenge_template": {
            "version": "v1",
            "source_revision": "sha256:" + "b" * 64,
            "evidence_fidelity": "complete",
            "future_utility": "none",
            "checks": {
                "user_correction": "absent",
                "explicit_decision": "absent",
                "successful_solution": "absent",
                "repeated_failure": "absent",
                "rule_or_preference": "absent",
                "reusable_workflow_or_fact": "absent",
                "version_or_migration": "absent",
                "unfinished_handoff": "absent",
            },
            "inspected_exchange_refs": [
                {"exchange_index": 1, "content_sha256": "c" * 64},
            ],
        },
        "semantic_decision_exchanges": [],
    }


class _Script:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[NativeDispatchRequest] = []

    def __call__(self, request: NativeDispatchRequest):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _exact(decision: object, *, output_tokens: int = 4) -> tuple[object, NativeDispatchResult]:
    return decision, NativeDispatchResult(
        status="completed",
        input_tokens=10,
        output_tokens=output_tokens,
        duration_seconds=1.0,
        usage_exact=True,
    )


def _provider(host: str = "fake-host") -> HostStructuredCliProvider:
    return HostStructuredCliProvider(host_client=host, executable="not-a-real-host")


def _arm(provider: HostStructuredCliProvider, data_dir: Path, config: MergedConfig, transport, **kwargs):
    binding = bind_maintenance_task(
        data_dir=data_dir,
        host_client=provider.host_client,
        config=config,
        trigger_id=kwargs.pop("trigger_id", "trigger-1"),
        dispatch_generation=kwargs.pop("dispatch_generation", "generation-1"),
    )
    provider.bind_task_budget(
        binding,
        phase=kwargs.pop("phase", "source"),
        slice_id=kwargs.pop("slice_id", "slice-1"),
        retry_of=kwargs.pop("retry_of", None),
        input_capability=fake_input_capability(provider.host_client, 1000),
        output_limit_surface=fake_output_limit_surface(provider.host_client),
        explicit_fake_transport=transport,
    )
    return binding


def _forbid_transport(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    reached: list[str] = []

    def boom(*_args, **_kwargs):
        reached.append("transport")
        raise AssertionError("native transport ran")

    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_structured_cli.subprocess.Popen", boom,
    )
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.codex_app_server.CodexAppServer.run", boom,
    )
    return reached


@pytest.mark.parametrize("host", _PRODUCTION_HOSTS)
def test_production_methods_refuse_before_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: str,
) -> None:
    reached = _forbid_transport(monkeypatch)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    provider = _provider(host)
    with pytest.raises(ProviderError) as missing:
        provider.decide(_decide_manifest(), runtime_dir=runtime)
    assert missing.value.failure_reason == "task_binding_missing"
    assert missing.value.kind == "setup_required"

    binding = bind_maintenance_task(
        data_dir=tmp_path / "data",
        host_client=host,
        config=MergedConfig(task_model_budget_host_max_output_tokens=50),
        trigger_id="trigger-1",
        dispatch_generation="generation-1",
    )
    provider.bind_task_budget(binding, phase="source", slice_id="source-decide:job")
    with pytest.raises(ProviderError) as closed:
        provider.verify({}, runtime_dir=runtime)
    assert closed.value.failure_reason == "host_output_limit_unsupported"
    assert not reached

    with pytest.raises(TaskBudgetRefusal) as doubled:
        provider.bind_task_budget(
            binding,
            phase="source",
            slice_id="source-decide:job",
            explicit_fake_transport=lambda _request: _exact(_empty_review()),
            input_capability=None,
        )
    assert doubled.value.code == "host_output_limit_unsupported"


def test_fake_host_reuses_one_scope_and_keeps_real_accounting(tmp_path: Path) -> None:
    script = _Script([
        _exact(_empty_review()),
        _exact(CandidateVerificationDecision(points=[])),
        _exact(AssimilationDecision(points=[])),
    ])
    config = _budget_config(task_model_budget_max_calls=2)
    data = tmp_path / "data"
    first = _provider()
    second = _provider()
    binding = _arm(first, data, config, script, slice_id="source-decide:job")
    runtime_a = tmp_path / "runtime-a"
    runtime_b = tmp_path / "runtime-b"
    runtime_a.mkdir()
    runtime_b.mkdir()
    decided = first.decide(_decide_manifest(), runtime_dir=runtime_a)
    assert decided.decision.semantic_review.promotion_decision == "no_promotion"
    _arm(
        second, data, config, script, phase="dream", slice_id="dream-continue",
        retry_of=first.last_task_budget_call_id(),
    )
    verified = second.verify({}, runtime_dir=runtime_b)
    assert isinstance(verified.decision, CandidateVerificationDecision)
    with pytest.raises(ProviderError) as exhausted:
        second.assimilate({}, runtime_dir=runtime_b)
    assert exhausted.value.failure_reason == "call_budget_exhausted"
    assert len(script.requests) == 2
    receipt = read_task_budget_receipt(data, binding.task_scope)
    assert receipt is not None
    assert receipt["task_scope"] == maintenance_task_scope("trigger-1", "generation-1")
    assert [call["runtime_dir"] for call in receipt["calls"]] == [str(runtime_a), str(runtime_b)]
    assert receipt["calls"][1]["retry_of"] == receipt["calls"][0]["call_id"]
    assert receipt["calls"][1]["phase"] == "dream"
    assert receipt["coverage"]["max_seconds_includes_lifecycle_wall_wait"] is False
    assert task_budget_receipt_path(data, binding.task_scope).is_file()


def test_time_output_and_unknown_holds_stop_the_next_call(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    time_script = _Script([_exact(_empty_review())])
    time_provider = _provider()
    _arm(
        time_provider, tmp_path / "time", _budget_config(task_model_budget_max_seconds=5),
        time_script, trigger_id="time-task",
    )
    with pytest.raises(ProviderError) as timed:
        time_provider.decide(_decide_manifest(), runtime_dir=runtime)
    assert timed.value.failure_reason == "time_budget_exhausted"
    assert time_script.requests == []

    over = _Script([
        _exact(CandidateVerificationDecision(points=[]), output_tokens=5),
        _exact(CandidateVerificationDecision(points=[])),
    ])
    over_provider = _provider()
    _arm(
        over_provider, tmp_path / "over",
        _budget_config(task_model_budget_host_max_output_tokens=4),
        over, trigger_id="over-task", slice_id="source-verify",
    )
    over_provider.verify({}, runtime_dir=runtime)
    with pytest.raises(ProviderError) as held:
        over_provider.verify({}, runtime_dir=runtime)
    assert held.value.failure_reason == "remaining_not_demonstrable"
    assert len(over.requests) == 1

    unknown = _Script([RuntimeError("transport failed closed"), _exact(AssimilationDecision(points=[]))])
    unknown_provider = _provider()
    _arm(
        unknown_provider, tmp_path / "unknown", _budget_config(), unknown,
        trigger_id="unknown-task", slice_id="source-assimilate",
    )
    with pytest.raises(RuntimeError, match="transport failed closed"):
        unknown_provider.assimilate({}, runtime_dir=runtime)
    with pytest.raises(ProviderError) as blocked:
        unknown_provider.assimilate({}, runtime_dir=runtime)
    assert blocked.value.failure_reason == "remaining_not_demonstrable"
    assert len(unknown.requests) == 1


def test_codex_start_threads_output_argv_and_spawn_is_the_only_seam(tmp_path: Path) -> None:
    executable = tmp_path / "codex-double"
    executable.write_bytes(b"not-a-host")
    recorded: list[list[str]] = []

    def stop(command, cwd, env):
        del cwd, env
        recorded.append(list(command))
        raise ProviderError("stopped before a process", kind="setup_required")

    server = CodexAppServer(
        str(executable),
        scope_factory=lambda *_args, **_kwargs: pytest.fail("scope starts after spawn"),
        remove_directory=lambda _path: None,
        poll_seconds=0.2,
    )
    server._spawn = stop  # type: ignore[method-assign]
    data = tmp_path / "data"
    data.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    with pytest.raises(ProviderError, match="stopped before a process"):
        server._start(
            runtime, {}, [], "instructions", data,
            time.monotonic() + 5, None, {}, ("--max-output-tokens", "4"),
        )
    assert recorded[0][0] == str(executable)
    assert recorded[0][-2:] == ["--max-output-tokens", "4"]
    assert server.scope_factory is not None


def test_public_config_writes_task_budget_and_reloads_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    untouched = tmp_path / "empty"
    untouched.mkdir()
    defaults = load_merged_config(untouched)
    assert defaults.task_model_budget_max_calls == 64
    assert defaults.cost_budget_wake_tokens == 2000
    assert defaults.cost_budget_search_tokens == 1200
    assert defaults.cost_budget_file_context_tokens == 900
    assert defaults.cost_budget_dream_tokens == 2000
    assert defaults.cost_budget_distill_tokens == 3000
    assert task_budget_coverage(defaults)["task_bounds"]["max_seconds"]["includes_lifecycle_wall_wait"] is False
    user = home / ".harness-mem" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        "[cost_budget]\nwake_tokens = 1500\n[task_model_budget]\nmax_calls = 2\n",
        encoding="utf-8",
    )
    (project / ".harness-mem.toml").write_text("[task_model_budget]\nmax_calls = 5\n", encoding="utf-8")
    loaded = load_merged_config(project)
    assert loaded.task_model_budget_max_calls == 5
    assert loaded.cost_budget_wake_tokens == 1500
    assert cmd_config_set("task_model_budget.max_calls", "4", "project", str(project)) == 0
    assert capsys.readouterr().err == ""
    written = set_value(scope="project", project_root=project, key_path="capture.enabled", value="false")
    assert "enabled = false" in written.read_text(encoding="utf-8")
    reloaded = load_merged_config(project)
    assert reloaded.capture_enabled is False
    assert reloaded.task_model_budget_max_calls == 4
    assert reloaded.cost_budget_search_tokens == 1200
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / ".harness-mem.toml").write_text("[task_model_budget]\nmax_calls = 0\n", encoding="utf-8")
    with pytest.raises(ConfigValidationError):
        load_merged_config(invalid)
    assert cmd_config_list(str(project)) == 0
    assert "task_model_budget.max_calls" in capsys.readouterr().out


def test_qualification_sample_refuses_real_host_and_keeps_fake_shape(tmp_path: Path, monkeypatch) -> None:
    from harness_mem.autonomous.executors import task_budget

    original_arm = task_budget.arm_provider_maintenance_task

    def strict_arm(*args, **kwargs):
        kwargs["config"] = MergedConfig(task_model_budget_host_max_output_tokens=50)
        return original_arm(*args, **kwargs)

    monkeypatch.setattr(task_budget, "arm_provider_maintenance_task", strict_arm)
    reached = _forbid_transport(monkeypatch)
    report_path = tmp_path / "reports" / "model.json"
    provider = _provider("codex")
    report = run_model_samples(output_path=report_path, provider=provider, fixture_ids=("F1",))
    sample = report["samples"][0]
    assert report["status"] == "failed"
    assert sample["status"] == "failed"
    assert sample["schema_valid"] is False
    assert sample["attempt_count"] == 1
    assert set(sample["error"]) == {"kind", "message"}
    assert sample["error"]["kind"] == "setup_required"
    assert "host_max_output_tokens" in sample["error"]["message"]
    assert "wall_duration_seconds" not in sample
    scope = maintenance_task_scope("qualification-F1", sample["manifest_sha256"][:32])
    assert not task_budget_receipt_path(report_path.parent, scope).is_file()
    assert not reached

    class _Plain:
        def decide(self, _manifest, *, runtime_dir: Path):
            assert runtime_dir.parent == (tmp_path / "plain.json").parent
            raise ProviderError("stop after path check", kind="setup_required")

    plain = run_model_samples(
        output_path=tmp_path / "plain.json", provider=_Plain(), fixture_ids=("F1",),
    )
    plain_sample = plain["samples"][0]
    assert set(plain_sample) == {
        "fixture_id", "status", "manifest_sha256", "fixture_catalog",
        "schema_valid", "attempt_count", "error",
    }
    assert plain_sample["error"] == {"kind": "setup_required", "message": "stop after path check"}
    assert "wall_duration_seconds" not in plain_sample


def _forbid_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail("native executor is not part of manual finalization")

    monkeypatch.setattr(
        "harness_mem.autonomous.executors.registry.build_semantic_executor", forbidden,
    )
    for method in ("decide", "verify", "assimilate"):
        monkeypatch.setattr(
            "harness_mem.autonomous.executors.host_structured_cli.HostStructuredCliProvider." + method,
            forbidden,
        )


def _judgment(text: str, **extra: object) -> dict[str, object]:
    point: dict[str, object] = {
        "candidate_index": 0,
        "semantic_support": "supported",
        "future_scope": "durable",
        "source_use": "reusable_knowledge",
        "reason": "The reopened repository text supports this exact statement.",
        "scope_segments": [{
            "text": text,
            "source_use": "reusable_knowledge",
            "future_scope": "durable",
            "standalone": True,
            "content_role": "claim",
            "source_support": "supported",
        }],
    }
    point.update(extra)
    return {"points": [point]}


def _statements(backend) -> list[str]:
    import asyncio
    entries = asyncio.run(backend.structured_store.knowledge_store.list_entries("project"))
    return [entry.statement for entry in entries]


def _memory_review(packet: dict) -> dict:
    return _HELPERS["_memory_review"](packet)


def test_govern_decide_requires_a_real_judgment(manual_fixture, monkeypatch) -> None:
    _forbid_executor(monkeypatch)
    backend, root, write = manual_fixture
    assert MergedConfig().distill_autonomous_enabled is False
    write("a", "Adopt the explicit local cache policy.")
    from harness_mem.mcp import tool_handlers
    from harness_mem.mcp.session_handlers import tool_inspect_sessions

    handlers = tool_handlers.build_tool_handlers()
    packet = handlers["prepare_session_distill"](
        project_name="project", project_root=str(root),
        batch_sessions=tool_inspect_sessions(str(root), clients=["cursor"])["sessions"],
    )
    assert packet["success"], packet
    statement = "The service retains only verified current cache entries."
    title = "Current cache policy"
    policy = root / "Current-cache-policy.txt"
    policy.write_text(statement, encoding="utf-8")
    import hashlib
    suggested = handlers["govern_memory"](action="suggest", arguments={
        "kind": "memory", "project_name": "project", "category": "decision", "content": statement,
        "source": "policy.txt", "distill_job_id": packet["distill_job_id"],
        "evidence_basis": "repository", "verification_outcome": "verified",
        "verification_refs": [{"kind": "repository", "locator": policy.name,
            "content_sha256": hashlib.sha256(policy.read_bytes()).hexdigest()}],
        "assimilation_disposition": "add", "assimilation_reason": "Verified independent current project requirement.",
        "canonical_title": title, "topic_path": ["Progress"], "target_knowledge": [],
    })
    assert suggested["success"], suggested
    items = [{
        "title": title, "statement": statement, "topic_path": ["Progress"],
        "claim_kind": "implementation_fact",
    }]
    base = {
        "kind": "knowledge", "project_name": "project", "decision": "confirm",
        "candidate_id": suggested["entry_id"], "disposition": "add",
        "reason": "Apply the verified source.", "knowledge_items": items,
    }
    missing = handlers["govern_memory"](action="decide", arguments=dict(base))
    assert missing.get("success") is False
    assert missing["reason_codes"] == ["final_scope_judgment_required"]
    proof = handlers["govern_memory"](action="decide", arguments={
        **base, "final_scope_judgment": "fsv_" + "ab" * 30,
    })
    assert proof["reason_codes"] == ["final_scope_proof_string_rejected"]
    only_proof = handlers["govern_memory"](action="decide", arguments={
        **base, "final_scope_judgment": {"proof": "fsv_" + "a" * 60},
    })
    assert only_proof["reason_codes"] == ["final_scope_proof_string_rejected"]
    negative = dict(_judgment(f"{title}\n{statement}"))
    negative["points"][0]["semantic_support"] = "contradicted"
    negative["points"][0]["scope_segments"][0]["source_support"] = "contradicted"
    rejected = handlers["govern_memory"](action="decide", arguments={
        **base, "final_scope_judgment": negative,
    })
    assert rejected["reason_codes"] == ["final_scope_judgment_rejected"]
    assert _statements(backend) == []

    accepted = handlers["govern_memory"](action="decide", arguments={
        **base, "final_scope_judgment": _judgment(f"{title}\n{statement}"),
    })
    assert accepted["success"] is True, accepted
    assert _statements(backend) == [statement]

    old_statement = "The service saves a signed sample once per day."
    old = _HELPERS["_seed_readable_memory"](
        backend, root, title="Signed sample", statement=old_statement,
    )
    successor = (
        "The service saves a signed sample once per day and the retention "
        "window is explicitly undecided."
    )
    version = target_version({
        "title": old.title, "statement": old.statement,
        "topic_path": list(old.module_path), "source_report": None,
    })
    meaning = {
        "relationship": "preserves_applicable_meaning",
        "predecessor_conditions": ["signed sample"],
        "predecessor_statements": [old.statement],
        "predecessor_versions": [version],
        "successor_statements": [successor],
        "undecided_state": "explicitly undecided",
        "basis": "The successor keeps the signed sample and the undecided window.",
    }
    replace_suggested = _HELPERS["_suggest_readable_memory"](
        backend, root, packet, title="Signed sample", statement=successor,
        disposition="replace", targets=[{"title": old.title, "statement": old.statement}],
    )
    assert replace_suggested["success"], replace_suggested
    dropped = json.loads(json.dumps(meaning))
    dropped["relationship"] = "drops_applicable_meaning"
    dropped["predecessor_conditions"] = []
    dropped["undecided_state"] = None
    drop_response = handlers["govern_memory"](action="decide", arguments={
        "kind": "knowledge", "project_name": "project", "decision": "confirm",
        "candidate_id": replace_suggested["entry_id"], "disposition": "replace",
        "reason": "Replace the saved sample rule.",
        "knowledge_items": [{
            "title": "Signed sample", "statement": successor,
            "topic_path": ["Progress"], "claim_kind": "implementation_fact",
        }],
        "target_knowledge": [{"title": old.title, "statement": old.statement}],
        "final_scope_judgment": _judgment(f"Signed sample\n{successor}", update_meaning_judgment=dropped),
    })
    assert drop_response["reason_codes"] == ["final_scope_judgment_rejected"]
    assert old_statement in _statements(backend)
    assert successor not in _statements(backend)
    kept = handlers["govern_memory"](action="decide", arguments={
        "kind": "knowledge", "project_name": "project", "decision": "confirm",
        "candidate_id": replace_suggested["entry_id"], "disposition": "replace",
        "reason": "Replace the saved sample rule.",
        "knowledge_items": [{
            "title": "Signed sample", "statement": successor,
            "topic_path": ["Progress"], "claim_kind": "implementation_fact",
        }],
        "target_knowledge": [{"title": old.title, "statement": old.statement}],
        "final_scope_judgment": _judgment(f"Signed sample\n{successor}", update_meaning_judgment=meaning),
    })
    assert kept.get("success") is True, kept
    assert successor in _statements(backend)
    assert old_statement not in _statements(backend)
    assert "signed sample" in successor and "explicitly undecided" in successor
    import asyncio
    asyncio.run(backend.close())
    asyncio.run(backend.init())
    fresh = handlers["search_memory"](query="Signed sample", project_name="project", scope="project")
    assert fresh["memories"] == [{"title": "Signed sample", "statement": successor}]

    deleted_key = handlers["govern_memory"](action="decide", arguments={
        "kind": "knowledge", "decision": "delete", "project_name": "project",
        "target_knowledge": [{"title": old.title, "statement": successor}],
        "final_scope_judgment": _judgment(f"{old.title}\n{successor}"),
    })
    assert deleted_key.get("success") is False
    assert successor in _statements(backend)
    removed = handlers["govern_memory"](action="decide", arguments={
        "kind": "knowledge", "decision": "delete", "project_name": "project",
        "target_knowledge": [{"title": old.title, "statement": successor}],
    })
    assert removed["success"], removed
    assert successor not in _statements(backend)
    assert statement in _statements(backend)


def test_finalize_consumes_a_supplied_judgment_and_replays_completed(manual_fixture, monkeypatch) -> None:
    _forbid_executor(monkeypatch)
    backend, root, write = manual_fixture
    write("reviewed", "Adopt the reviewed cache rule.")
    from harness_mem.mcp import tool_handlers
    from harness_mem.mcp.session_handlers import tool_inspect_sessions

    packet = tool_handlers.tool_prepare_session_distill(
        project_name="project", project_root=str(root),
        batch_sessions=tool_inspect_sessions(str(root), clients=["cursor"])["sessions"],
    )
    assert packet["success"], packet
    title = "Reviewed cache entry"
    statement = "The service stores one reviewed cache entry."
    suggested = _HELPERS["_suggest_readable_memory"](
        backend, root, packet, title=title, statement=statement,
    )
    assert suggested["success"], suggested
    refused = tool_handlers.tool_finalize_session_distill(
        "project", packet["distill_job_id"],
        {**_memory_review(packet), "final_scope_judgment": None},
    )
    assert refused["success"] is False
    assert refused["reason_codes"] == ["final_scope_judgment_required"]
    refused_string = tool_handlers.tool_finalize_session_distill(
        "project", packet["distill_job_id"],
        {**_memory_review(packet), "final_scope_judgment": "fsv_" + "c" * 60},
    )
    assert refused_string["reason_codes"] == ["final_scope_proof_string_rejected"]
    assert statement not in _statements(backend)
    final = tool_handlers.tool_finalize_session_distill(
        "project", packet["distill_job_id"],
        {**_memory_review(packet), "final_scope_judgment": {
            suggested["entry_id"]: _judgment(f"{title}\n{statement}"),
        }},
    )
    assert final["success"], json.dumps(final, ensure_ascii=False)
    assert _statements(backend) == [statement]
    replay = tool_handlers.tool_finalize_session_distill(
        "project", packet["distill_job_id"], _memory_review(packet),
    )
    assert replay["success"] and replay["idempotent_replay"]


def test_finalize_replace_keeps_the_judged_condition(manual_fixture, monkeypatch) -> None:
    _forbid_executor(monkeypatch)
    backend, root, write = manual_fixture
    old_statement = "The service saves a signed sample once per day."
    old = _HELPERS["_seed_readable_memory"](
        backend, root, title="Signed sample", statement=old_statement,
    )
    write("replace", "Adopt the signed sample rule with its undecided window.")
    from harness_mem.mcp import tool_handlers
    from harness_mem.mcp.session_handlers import tool_inspect_sessions

    packet = tool_handlers.tool_prepare_session_distill(
        project_name="project", project_root=str(root),
        batch_sessions=tool_inspect_sessions(str(root), clients=["cursor"])["sessions"],
    )
    assert packet["success"], packet
    successor = (
        "The service saves a signed sample once per day and the retention "
        "window is explicitly undecided."
    )
    suggested = _HELPERS["_suggest_readable_memory"](
        backend, root, packet, title="Signed sample", statement=successor,
        disposition="replace", targets=[{"title": old.title, "statement": old.statement}],
    )
    assert suggested["success"], suggested
    version = target_version({
        "title": old.title, "statement": old.statement,
        "topic_path": list(old.module_path), "source_report": None,
    })
    meaning = {
        "relationship": "preserves_applicable_meaning",
        "predecessor_conditions": ["signed sample"],
        "predecessor_statements": [old.statement],
        "predecessor_versions": [version],
        "successor_statements": [successor],
        "undecided_state": "explicitly undecided",
        "basis": "The successor keeps the signed sample and the undecided window.",
    }
    dropped = json.loads(json.dumps(meaning))
    dropped["relationship"] = "drops_applicable_meaning"
    dropped["predecessor_conditions"] = []
    dropped["undecided_state"] = None
    scope = f"Signed sample\n{successor}"
    dropped_final = tool_handlers.tool_finalize_session_distill(
        "project", packet["distill_job_id"],
        {**_memory_review(packet), "final_scope_judgment": {
            suggested["entry_id"]: _judgment(scope, update_meaning_judgment=dropped),
        }},
    )
    assert dropped_final["success"] is False
    assert dropped_final["reason_codes"] == ["final_scope_judgment_rejected"]
    assert _statements(backend) == [old_statement]
    kept = tool_handlers.tool_finalize_session_distill(
        "project", packet["distill_job_id"],
        {**_memory_review(packet), "final_scope_judgment": {
            suggested["entry_id"]: _judgment(scope, update_meaning_judgment=meaning),
        }},
    )
    assert kept["success"], json.dumps(kept, ensure_ascii=False)
    assert _statements(backend) == [successor]
    assert "signed sample" in successor and "explicitly undecided" in successor


@pytest.mark.parametrize("change", ("task", "host", "config", "mutated-config", "data-dir"))
def test_fake_adapter_capabilities_never_cross_binding_scope(tmp_path, monkeypatch, change):
    from dataclasses import replace

    reached = _forbid_transport(monkeypatch)
    provider = _provider()
    script = _Script([_exact(CandidateVerificationDecision(points=[]))])
    config = _budget_config()
    original = _arm(provider, tmp_path / "data", config, script)
    if change == "task":
        changed = replace(original, task_scope="different-task")
    elif change == "host":
        provider.host_client = "other-fake"
        changed = replace(original, host_client="other-fake")
    elif change == "config":
        changed = replace(original, config=_budget_config(task_model_budget_max_calls=9))
    elif change == "mutated-config":
        config.extras["adapter"] = {"revision": 2}
        changed = original
    else:
        changed = replace(original, data_dir=tmp_path / "other-data")
    provider.bind_task_budget(changed, phase="dream", slice_id="next")
    assert provider._input_capability is None
    assert provider._output_surface is None
    assert provider._explicit_fake_transport is None
    with pytest.raises(ProviderError) as refused:
        provider.verify({}, runtime_dir=tmp_path / "runtime")
    assert refused.value.failure_reason == "host_output_limit_unsupported"
    assert script.requests == []
    assert reached == []


def test_fake_adapter_rebind_keeps_one_task_ledger(tmp_path, monkeypatch):
    from dataclasses import replace
    from harness_mem.autonomous.worker import _invoke_provider

    reached = _forbid_transport(monkeypatch)
    provider = _provider()
    config = _budget_config(task_model_budget_max_calls=2)
    script = _Script([_exact(CandidateVerificationDecision(points=[])) for _ in range(2)])
    binding = _arm(provider, tmp_path / "data", config, script)
    # A newly created equivalent binding is the same explicit task.
    provider.attach_maintenance_binding(replace(binding, config=_budget_config(task_model_budget_max_calls=2)))
    for phase in ("source", "dream"):
        _invoke_provider(provider, "verify", {}, runtime_dir=tmp_path / phase,
                         heartbeat=None, phase=phase, slice_id=phase + "-slice")
    with pytest.raises(ProviderError) as refused:
        _invoke_provider(provider, "verify", {}, runtime_dir=tmp_path / "third",
                         heartbeat=None, phase="dream", slice_id="third-slice")
    assert refused.value.failure_reason == "call_budget_exhausted"
    assert len(script.requests) == 2
    assert [row["phase"] for row in read_task_budget_receipt(binding.data_dir, binding.task_scope)["calls"]] == ["source", "dream"]
    assert reached == []
