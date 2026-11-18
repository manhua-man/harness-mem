"""Observed native usage through production provider methods; no CLI is started."""

from __future__ import annotations

from dataclasses import replace

import pytest

from harness_mem.autonomous.authorization import background_status
from harness_mem.autonomous.executors.codex_app_server import CodexAppServer
from harness_mem.autonomous.executors.host_structured_cli import HostStructuredCliProvider
from harness_mem.autonomous.executors.task_budget import (
    bind_maintenance_task,
    read_task_budget_receipt,
    task_budget_coverage,
)
from harness_mem.autonomous.models import (
    AgentExtractionDecision,
    AssimilationDecision,
    CandidateVerificationDecision,
)
from harness_mem.autonomous.provider import ProviderError, ProviderResult
from harness_mem.config.merge import MergedConfig

HOSTS = ("codex", "claude-code", "hermes", "opencode", "antigravity")


@pytest.fixture(autouse=True)
def forbid_real_native_transport(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("real native transport is forbidden in observed-budget fixtures")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr(CodexAppServer, "run", forbidden)


def _review():
    return AgentExtractionDecision.model_validate({
        "review": {
            "summary": "No durable fact.", "final_request": "Record nothing.",
            "actual_result": "Nothing recorded.",
            "no_candidate_reason": "This isolated call contains no durable project fact.",
        },
        "points": [],
    })


def _manifest():
    return {
        "zero_candidate_challenge_template": {
            "version": "v1", "source_revision": "sha256:" + "b" * 64,
            "evidence_fidelity": "complete", "future_utility": "none",
            "checks": {key: "absent" for key in (
                "user_correction", "explicit_decision", "successful_solution",
                "repeated_failure", "rule_or_preference", "reusable_workflow_or_fact",
                "version_or_migration", "unfinished_handoff",
            )},
            "inspected_exchange_refs": [{"exchange_index": 1, "content_sha256": "c" * 64}],
        },
        "semantic_decision_exchanges": [],
    }


def _result(decision=None, *, inputs=30, outputs=7, seconds=1.2, valid=True):
    return ProviderResult(
        decision=decision or CandidateVerificationDecision(points=[]),
        provider="host-cli", model=None, duration_seconds=seconds,
        input_sha256="a" * 64, response_sha256="b" * 64,
        input_tokens=inputs, output_tokens=outputs,
        total_tokens=inputs + outputs if inputs is not None and outputs is not None else None,
        event_count=1, schema_valid=valid,
    )


def _armed(tmp_path, *, config=None, host="codex", phase="source", slice_id="slice-1"):
    provider = HostStructuredCliProvider(host_client=host, executable="never-start-this-host")
    binding = bind_maintenance_task(
        data_dir=tmp_path / "data", host_client=host, config=config or MergedConfig(),
        trigger_id="natural-source", dispatch_generation="same-generation",
    )
    provider.bind_task_budget(binding, phase=phase, slice_id=slice_id)
    return provider, binding


@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize("method", ("decide", "verify", "assimilate"))
def test_production_methods_dispatch_under_defaults_without_fake_capability(tmp_path, monkeypatch, host, method):
    provider, binding = _armed(tmp_path, host=host)
    reached = []
    decision = {
        "decide": _review(), "verify": CandidateVerificationDecision(points=[]),
        "assimilate": AssimilationDecision(points=[]),
    }[method]

    def native(_manifest, **kwargs):
        reached.append(kwargs)
        assert kwargs["output_limit_argv"] == ()
        return _result(decision)

    monkeypatch.setattr(provider, "_run_native_body", native)
    result = getattr(provider, method)(_manifest() if method == "decide" else {}, runtime_dir=tmp_path / "runtime")
    assert result.input_tokens == 30
    assert len(reached) == 1
    receipt = read_task_budget_receipt(binding.data_dir, binding.task_scope)
    assert len(receipt["calls"]) == 1
    call = receipt["calls"][0]
    assert call["usage_exact"] is True
    assert call["usage"]["input_tokens"] == 30
    assert call["usage"]["output_tokens"] == 7
    assert call["model_completion"] is True
    assert call["input_bound"]["max_complete_input_tokens"] is None
    assert call["input_bound"]["adapter_enforces_bound"] is False


def test_fresh_providers_share_source_dream_and_retry_ledger(tmp_path, monkeypatch):
    config = MergedConfig(task_model_budget_max_calls=2)
    first, binding = _armed(tmp_path, config=config)
    monkeypatch.setattr(first, "_run_native_body", lambda *_a, **_kw: _result(inputs=30, outputs=7))
    first.verify({}, runtime_dir=tmp_path / "first")
    second, reopened = _armed(tmp_path, config=config, phase="dream", slice_id="continuation")
    second.bind_task_budget(reopened, phase="dream", slice_id="continuation", retry_of=first.last_task_budget_call_id())
    reached = []

    def native(*_a, **_kw):
        reached.append(True)
        return _result(inputs=40, outputs=8)

    monkeypatch.setattr(second, "_run_native_body", native)
    second.verify({}, runtime_dir=tmp_path / "second")
    with pytest.raises(ProviderError) as denied:
        second.verify({}, runtime_dir=tmp_path / "third")
    assert denied.value.failure_reason == "call_budget_exhausted"
    assert reached == [True]
    receipt = read_task_budget_receipt(binding.data_dir, binding.task_scope)
    assert [row["phase"] for row in receipt["calls"]] == ["source", "dream"]
    assert receipt["calls"][1]["retry_of"] == receipt["calls"][0]["call_id"]
    assert sum(row["usage"]["input_tokens"] for row in receipt["calls"]) == 70
    assert receipt["phase_handoff_resets_budget"] is False


@pytest.mark.parametrize("field,threshold,reason", (
    ("max_input_tokens", 20, "input_budget_exhausted"),
    ("max_output_tokens", 5, "output_budget_exhausted"),
))
def test_final_token_overshoot_preserves_result_but_denies_next_call(tmp_path, monkeypatch, field, threshold, reason):
    provider, binding = _armed(tmp_path, config=MergedConfig(**{"task_model_budget_" + field: threshold}))
    reached = []

    def native(*_a, **_kw):
        reached.append(True)
        return _result()

    monkeypatch.setattr(provider, "_run_native_body", native)
    accepted = provider.verify({}, runtime_dir=tmp_path / "first")
    assert accepted.schema_valid is True
    receipt = read_task_budget_receipt(binding.data_dir, binding.task_scope)
    assert receipt["calls"][0]["model_completion"] is True
    assert receipt["calls"][0]["usage"][field.removeprefix("max_")] > threshold
    with pytest.raises(ProviderError) as denied:
        provider.verify({}, runtime_dir=tmp_path / "second")
    assert denied.value.failure_reason == reason
    assert reached == [True]


def test_unknown_native_failure_stops_future_calls(tmp_path, monkeypatch):
    provider, binding = _armed(tmp_path)
    reached = []

    def native(*_a, **_kw):
        reached.append(True)
        raise ProviderError("native failure", kind="transient", attempt_results=(
            _result(inputs=None, outputs=None, valid=False),
        ))

    monkeypatch.setattr(provider, "_run_native_body", native)
    with pytest.raises(ProviderError, match="native failure"):
        provider.verify({}, runtime_dir=tmp_path / "first")
    with pytest.raises(ProviderError) as denied:
        provider.verify({}, runtime_dir=tmp_path / "second")
    assert denied.value.failure_reason == "remaining_not_demonstrable"
    assert reached == [True]
    receipt = read_task_budget_receipt(binding.data_dir, binding.task_scope)
    assert receipt["calls"][0]["usage_exact"] is False
    assert receipt["calls"][0]["model_completion"] is False


def test_known_schema_failure_consumes_actual_usage_then_permits_retry(tmp_path, monkeypatch):
    provider, binding = _armed(tmp_path)
    failure = _result(inputs=10, outputs=3, valid=False)

    def native(*_a, **_kw):
        raise ProviderError("invalid schema", kind="unrecoverable", attempt_results=(failure,))

    monkeypatch.setattr(provider, "_run_native_body", native)
    with pytest.raises(ProviderError, match="invalid schema"):
        provider.verify({}, runtime_dir=tmp_path / "first")
    monkeypatch.setattr(provider, "_run_native_body", lambda *_a, **_kw: _result(inputs=20, outputs=4))
    provider.verify({}, runtime_dir=tmp_path / "retry")
    receipt = read_task_budget_receipt(binding.data_dir, binding.task_scope)
    assert [row["status"] for row in receipt["calls"]] == ["failed", "completed"]
    assert sum(row["usage"]["input_tokens"] for row in receipt["calls"]) == 30
    assert receipt["calls"][0]["model_completion"] is False


@pytest.mark.parametrize("host", HOSTS)
def test_explicit_strict_cap_still_denies_production_before_native_body(tmp_path, monkeypatch, host):
    provider, binding = _armed(tmp_path, host=host, config=MergedConfig(task_model_budget_host_max_output_tokens=10))
    monkeypatch.setattr(provider, "_run_native_body", lambda *_a, **_kw: pytest.fail("strict refusal must precede transport"))
    with pytest.raises(ProviderError) as denied:
        provider.verify({}, runtime_dir=tmp_path / "runtime")
    assert denied.value.failure_reason == "host_output_limit_unsupported"
    assert read_task_budget_receipt(binding.data_dir, binding.task_scope) is None


def test_finite_defaults_and_ready_status_do_not_claim_hard_token_caps(monkeypatch):
    config = MergedConfig(distill_autonomous_enabled=True)
    assert (config.task_model_budget_max_calls, config.task_model_budget_max_seconds,
            config.task_model_budget_max_input_tokens, config.task_model_budget_max_output_tokens,
            config.task_model_budget_host_max_output_tokens) == (64, 3600, 2_000_000, 128_000, None)
    monkeypatch.setattr("harness_mem.autonomous.executors.host_cli._resolve_executable", lambda _: "present")
    for view in (config, config.to_runtime_config()):
        assert background_status(view, client="codex").ready is True
    coverage = task_budget_coverage(config)
    assert coverage["missing_bounds"] == []
    assert coverage["usage_from_text_length"] is False
    assert coverage["task_bounds"]["max_seconds"]["includes_lifecycle_wall_wait"] is False
    assert background_status(replace(config, distill_autonomous_enabled=False), client="codex").ready is False


def test_codex_cached_and_reasoning_usage_are_subsets_not_extra_tokens():
    usage = {"inputTokens": 50, "cachedInputTokens": 40, "outputTokens": 10,
             "reasoningOutputTokens": 6, "totalTokens": 60}
    record = {"responses": [{"usage": usage}, {"usage": usage}], "terminal": "completed"}
    assert CodexAppServer.usage(record) == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    record["native_errors"] = [{"willRetry": True}]
    assert CodexAppServer.usage(record) == {"input_tokens": None, "output_tokens": None, "total_tokens": None}
