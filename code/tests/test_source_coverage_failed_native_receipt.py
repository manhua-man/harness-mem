"""Failed source attempts keep exact native bindings without writing truth."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness_mem.autonomous import worker
from harness_mem.autonomous.provider import ProviderError, ProviderResult


def invoke(monkeypatch, implementation, save):
    monkeypatch.setattr(worker, "_run_source_coverage_attempt", implementation)
    return worker.run_source_coverage_attempt(
        object(), provider=SimpleNamespace(_last_budget_call_id="budget-call"),
        project_name="demo", project_root=Path("demo"),
        prepared={"job": SimpleNamespace(id="source-job")}, attempt_id="binding",
        state={}, save=save, heartbeat=lambda: None, runtime_dir=Path("scratch"),
    )


def test_failed_native_result_is_retained_before_original_error_propagates(monkeypatch):
    native = {"call_id": "native-call", "thread_id": "thread", "turn_id": "turn",
              "terminal": None, "status": "failed", "usage": {"input_tokens": None}}
    result = ProviderResult(None, "codex", "model", 300.0, "a" * 64, "b" * 64,
                            None, None, None, 4, schema_valid=False,
                            host_client="codex", native_attempts=(native,))
    error = ProviderError("private original detail must not enter receipt", kind="transient",
                          failure_reason="native_request_deadline", exit_code=4,
                          attempt_results=(result,), native_attempts=(native,))

    def fail(*_args, **_kwargs):
        raise error

    saved = []
    with pytest.raises(ProviderError) as caught:
        invoke(monkeypatch, fail, saved.append)
    assert caught.value is error
    assert len(saved) == 1
    update = saved[0]
    assert update.pop("_provider_error") is error
    assert update["status"] == "failed"
    assert update["reason_code"] == "native_request_deadline"
    receipt = update["_receipt"]
    assert receipt["phase"] == "provider_failure"
    assert receipt["budget_call_id"] == "budget-call"
    assert receipt["source_job_id"] == "source-job" and receipt["attempt_id"] == "binding"
    assert receipt["attempt_results"] == [result.receipt()]
    assert receipt["native_attempts"] == [native]
    assert "private original detail" not in str(update)


def test_receipt_failure_cannot_replace_original_provider_failure(monkeypatch):
    error = ProviderError("original", kind="transient")
    receipt_error = ValueError("checkpoint changed")

    def fail(*_args, **_kwargs):
        raise error

    def reject(_update):
        raise receipt_error

    with pytest.raises(ProviderError) as caught:
        invoke(monkeypatch, fail, reject)
    assert caught.value is error and error.__cause__ is receipt_error


def test_success_does_not_add_a_failure_receipt(monkeypatch):
    saved = []

    def succeed(*_args, **kwargs):
        kwargs["save"]({"status": "applied"})

    invoke(monkeypatch, succeed, saved.append)
    assert saved == [{"status": "applied"}]


def test_nonprovider_failure_is_not_relabelled_native(monkeypatch):
    saved = []
    error = ValueError("source binding changed")

    def fail(*_args, **_kwargs):
        raise error

    with pytest.raises(ValueError) as caught:
        invoke(monkeypatch, fail, saved.append)
    assert caught.value is error and not saved


def test_predispatch_refusal_does_not_borrow_a_previous_call_id(monkeypatch):
    saved = []
    error = ProviderError("budget refuses transport", kind="unrecoverable",
                          failure_reason="unknown_usage")

    def fail(*_args, **_kwargs):
        raise error

    with pytest.raises(ProviderError):
        invoke(monkeypatch, fail, saved.append)
    assert saved[0]["_receipt"]["budget_call_id"] is None
    assert saved[0]["_receipt"]["attempt_results"] == []
