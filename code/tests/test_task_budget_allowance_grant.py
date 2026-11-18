"""Finite allowance accounting; isolated receipts and Python transport only."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from harness_mem.autonomous.executors.task_budget import (
    NativeDispatchResult, TaskBudgetRefusal, bind_maintenance_task,
    dispatch_with_task_budget, effective_task_budget_bounds,
    grant_maintenance_allowance, read_task_budget_receipt,
    task_budget_observation, task_budget_receipt_path,
)
from harness_mem.config.merge import MergedConfig


AUTH = {
    "kind": "current_agent_explicit_user_instruction",
    "instruction_sha256": hashlib.sha256("Continue this same maintenance task.".encode()).hexdigest(),
    "message_context": {"thread": "isolated-test", "message": "user-1"},
    "actor_chosen_limits": True,
    "human_specified_amounts": False,
}


def _binding(tmp_path, **limits):
    return bind_maintenance_task(
        data_dir=tmp_path, host_client="codex", trigger_id="original",
        dispatch_generation="generation", config=MergedConfig(**{
            "task_model_budget_max_calls": 2,
            "task_model_budget_max_seconds": 10,
            "task_model_budget_max_input_tokens": 100,
            "task_model_budget_max_output_tokens": 10,
            **limits,
        }),
    )


def _call(binding, *, output=11, seconds=1, transport=None):
    return dispatch_with_task_budget(
        binding, phase="dream", slice_id="same-slice", timeout_seconds=2,
        transport=transport or (lambda request: NativeDispatchResult(
            status="completed", input_tokens=3, output_tokens=output,
            duration_seconds=seconds, usage_exact=True,
        )),
    )


def _path(binding):
    return task_budget_receipt_path(binding.data_dir, binding.task_scope)


def _grant(binding, *, grant_id="allowance-1", additional=None, digest=None, auth=None):
    return grant_maintenance_allowance(
        binding, grant_id=grant_id,
        expected_receipt_sha256=digest or hashlib.sha256(_path(binding).read_bytes()).hexdigest(),
        additional_bounds=additional or {"max_output_tokens": 20, "max_seconds": 10},
        authorization=AUTH if auth is None else auth,
    )


def test_append_preserves_account_and_dispatch_uses_effective_bounds(tmp_path):
    binding = _binding(tmp_path)
    first = _call(binding).receipt
    original = deepcopy(first)
    with pytest.raises(TaskBudgetRefusal, match="output-token"):
        _call(binding)
    digest = hashlib.sha256(_path(binding).read_bytes()).hexdigest()
    granted = _grant(binding, digest=digest)
    assert {k: v for k, v in granted.items() if k != "allowance_grants"} == original
    assert granted["bounds"]["max_output_tokens"] == 10
    assert effective_task_budget_bounds(granted)["max_output_tokens"] == 30
    assert granted["allowance_grants"][0]["request"]["expected_receipt_sha256"] == digest
    assert _grant(binding, digest=digest) == granted
    assert len(_call(binding, output=4).receipt["calls"]) == 2
    current = read_task_budget_receipt(binding.data_dir, binding.task_scope)
    assert current["calls"][1]["cumulative_token_threshold_excess"]["output_tokens"] == 0
    # Exact retry stays idempotent after later calls; it cannot append again.
    assert _grant(binding, digest=digest) == current
    observed = task_budget_observation(binding.data_dir, "original", "generation")
    assert observed["effective_bounds"]["max_output_tokens"] == 30
    assert observed["original_bounds"]["max_output_tokens"] == 10
    with pytest.raises(TaskBudgetRefusal) as denied:
        _call(binding, output=1)
    assert denied.value.code == "call_budget_exhausted"


def test_multiple_grants_bind_prior_grant_and_call_prefix(tmp_path):
    binding = _binding(tmp_path)
    _call(binding)
    _grant(binding)
    _call(binding, output=20)
    granted = _grant(binding, grant_id="allowance-2", additional={"max_calls": 1, "max_output_tokens": 5})
    assert effective_task_budget_bounds(granted)["max_output_tokens"] == 35
    assert len(_call(binding, output=3).receipt["calls"]) == 3
    assert read_task_budget_receipt(binding.data_dir, binding.task_scope)["calls"][2][
        "cumulative_token_threshold_excess"]["output_tokens"] == 0


@pytest.mark.parametrize("change", [
    {"additional": {"host_max_output_tokens": 100}},
    {"additional": {"max_output_tokens": -1}},
    {"additional": {"max_seconds": float("inf")}},
    {"additional": {"max_calls": True}},
    {"additional": {"max_calls": 0}},
    {"auth": {}},
    {"auth": {**AUTH, "actor_chosen_limits": False}},
    {"auth": {**AUTH, "instruction_sha256": "wrong"}},
    {"auth": {**AUTH, "human_specified_amounts": True}},
    {"auth": {**AUTH, "message_context": ""}},
    {"digest": "0" * 64},
])
def test_invalid_requests_do_not_change_ledger(tmp_path, change):
    binding = _binding(tmp_path)
    _call(binding)
    before = _path(binding).read_bytes()
    with pytest.raises(TaskBudgetRefusal):
        _grant(binding, **change)
    assert _path(binding).read_bytes() == before


@pytest.mark.parametrize("mutation", ["reserved", "unknown", "malformed", "inexact", "exceeded", "nan"])
def test_active_unknown_or_invalid_usage_cannot_be_granted(tmp_path, mutation):
    binding = _binding(tmp_path)
    _call(binding)
    payload = json.loads(_path(binding).read_text())
    row = payload["calls"][0]
    if mutation in {"reserved", "unknown", "malformed"}:
        row["status"] = mutation
    elif mutation == "inexact":
        row["usage_exact"] = False
    elif mutation == "exceeded":
        row["bound_exceeded"] = True
    else:
        row["usage"]["duration_seconds"] = float("nan")
    _path(binding).write_text(json.dumps(payload), encoding="utf-8")
    before = _path(binding).read_bytes()
    with pytest.raises(TaskBudgetRefusal):
        _grant(binding)
    assert _path(binding).read_bytes() == before


@pytest.mark.parametrize("mutation", ["prior_call", "amount", "authorization", "effective", "duplicate", "shape"])
def test_tampered_grants_close_read_dispatch_and_observation(tmp_path, mutation):
    binding = _binding(tmp_path)
    _call(binding)
    granted = _grant(binding)
    grant = granted["allowance_grants"][0]
    if mutation == "prior_call":
        granted["calls"][0]["usage"]["output_tokens"] += 1
    elif mutation == "amount":
        grant["request"]["additional_bounds"]["max_output_tokens"] += 1
    elif mutation == "authorization":
        grant["request"]["authorization"]["instruction_sha256"] = "a" * 64
    elif mutation == "effective":
        grant["effective_bounds"]["max_output_tokens"] += 1
    elif mutation == "duplicate":
        granted["allowance_grants"].append(deepcopy(grant))
    else:
        granted["allowance_grants"] = "invalid"
    _path(binding).write_text(json.dumps(granted), encoding="utf-8")
    before = _path(binding).read_bytes()
    with pytest.raises(TaskBudgetRefusal):
        read_task_budget_receipt(binding.data_dir, binding.task_scope)
    with pytest.raises(TaskBudgetRefusal):
        _call(binding, transport=lambda _: pytest.fail("must refuse before transport"))
    observation = task_budget_observation(binding.data_dir, "original", "generation")
    assert observation["refusal"]["code"] == "allowance_grant_invalid"
    assert _path(binding).read_bytes() == before


def test_binding_or_original_bounds_change_refuses_and_grant_id_cannot_rebind(tmp_path):
    binding = _binding(tmp_path)
    _call(binding)
    _grant(binding)
    before = _path(binding).read_bytes()
    for changed in (replace(binding, host_client="hermes"), replace(
        binding, config=replace(binding.config, task_model_budget_max_seconds=100),
    )):
        with pytest.raises(TaskBudgetRefusal):
            _grant(changed, grant_id="other")
    with pytest.raises(TaskBudgetRefusal):
        _grant(binding, additional={"max_calls": 10})
    assert _path(binding).read_bytes() == before


def test_grant_never_creates_an_account(tmp_path):
    binding = _binding(tmp_path)
    with pytest.raises(TaskBudgetRefusal):
        _grant(binding, digest="a" * 64)
    assert not _path(binding).exists()


@pytest.mark.parametrize("limits,additional,code", [
    ({"task_model_budget_max_seconds": 2}, {"max_seconds": 2}, "time_budget_exhausted"),
    ({"task_model_budget_max_input_tokens": 3}, {"max_input_tokens": 3}, "input_budget_exhausted"),
    ({"task_model_budget_max_calls": 1}, {"max_calls": 1}, "call_budget_exhausted"),
])
def test_effective_bounds_cover_each_reservation_dimension(tmp_path, limits, additional, code):
    binding = _binding(tmp_path, task_model_budget_max_output_tokens=100, **limits)
    _call(binding, output=1, seconds=2)
    with pytest.raises(TaskBudgetRefusal) as denied:
        _call(binding, output=1)
    assert denied.value.code == code
    _grant(binding, additional=additional)
    assert len(_call(binding, output=1).receipt["calls"]) == 2


def test_stale_exact_hash_refuses_after_another_call(tmp_path):
    binding = _binding(tmp_path, task_model_budget_max_output_tokens=100)
    _call(binding, output=1)
    digest = hashlib.sha256(_path(binding).read_bytes()).hexdigest()
    _call(binding, output=1)
    before = _path(binding).read_bytes()
    with pytest.raises(TaskBudgetRefusal) as denied:
        _grant(binding, digest=digest)
    assert denied.value.code == "allowance_receipt_changed"
    assert _path(binding).read_bytes() == before


def test_actual_inflight_reservation_refuses_grant(tmp_path):
    binding = _binding(tmp_path)

    def transport(_request):
        before = _path(binding).read_bytes()
        with pytest.raises(TaskBudgetRefusal):
            _grant(binding)
        assert _path(binding).read_bytes() == before
        return NativeDispatchResult("completed", 1, 1, 1, True)

    result = _call(binding, transport=transport)
    assert result.receipt["calls"][0]["status"] == "completed"
    assert "allowance_grants" not in result.receipt
