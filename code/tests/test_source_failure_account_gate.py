"""Only exact terminal source-failure bookkeeping can preserve unknown usage."""
import asyncio

import pytest

from test_terminal_source_coverage import captured as captured, coverage as coverage, terminal as terminal
from harness_mem.autonomous.executors.task_budget import (
    NativeDispatchResult, dispatch_with_task_budget, read_task_budget_receipt,
    task_budget_receipt_path,
)
from harness_mem.commands.dream_continuation import _bound_source_account
from harness_mem.commands.dream_source_coverage import _digest


def prepare(terminal, *, known=False):
    backend, _root, _old, _carrier, _job, _provider, _config, bindings = terminal
    dispatch_with_task_budget(bindings[0], phase="dream", slice_id="source-coverage:original:attempt:decide",
        timeout_seconds=1, transport=lambda _: NativeDispatchResult(
            status="failed", input_tokens=5 if known else None,
            output_tokens=2 if known else None, duration_seconds=0.01 if known else None,
            usage_exact=known))
    receipt = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    last = receipt["calls"][-1]
    proof = dict(contract="source-failure-bookkeeping-v1", task_scope=receipt["task_scope"],
        ledger_sha256=_digest(receipt), failed_call_id=last["call_id"],
        failed_call_sha256=_digest(last), completed_prefix_sha256=_digest(receipt["calls"][:-1]))
    return receipt, proof


def bound(terminal, **kwargs):
    backend, root, old, _carrier, job, _provider, config, _bindings = terminal
    return asyncio.run(_bound_source_account(backend, run=old, project_name="demo",
        project_root=str(root), config=config, host_client="codex", source_job_id=job.id, **kwargs))


def test_exact_failure_bookkeeping_preserves_unknown_account_without_dispatch(terminal):
    backend, _root, old, _carrier, _job, _provider, _config, bindings = terminal
    receipt, proof = prepare(terminal)
    path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
    before = path.read_bytes()
    result, generation, _trigger = bound(terminal, require_remaining=False, failure_account=proof)
    assert result.id == old.id and generation == "original-generation"
    assert path.read_bytes() == before
    assert len(receipt["calls"]) == 2 and receipt["calls"][-1]["usage_exact"] is False
    with pytest.raises(ValueError, match="continuation_usage_unknown_or_active"):
        bound(terminal, require_remaining=True)


def test_exact_known_failure_can_only_persist_metadata_without_dispatch(terminal):
    backend, _root, old, _carrier, _job, _provider, _config, bindings = terminal
    receipt, proof = prepare(terminal, known=True)
    path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
    before = path.read_bytes()
    assert bound(terminal, require_remaining=False, failure_account=proof)[0].id == old.id
    assert path.read_bytes() == before and receipt["calls"][-1]["usage"]["output_tokens"] == 2
    with pytest.raises(ValueError, match="continuation_usage_unknown_or_active"):
        bound(terminal, require_remaining=True)


@pytest.mark.parametrize("fault", ["missing", "hash", "call", "prefix", "scope", "extra", "remaining", "exhausted"])
def test_failure_proof_is_not_an_inference_or_forged_account_permit(terminal, fault):
    _receipt, proof = prepare(terminal)
    kwargs = dict(require_remaining=False, failure_account=proof)
    if fault == "missing":
        kwargs.pop("failure_account")
    elif fault in {"hash", "call", "prefix", "scope"}:
        key = dict(hash="ledger_sha256", call="failed_call_id", prefix="completed_prefix_sha256", scope="task_scope")[fault]
        proof[key] = "changed"
    elif fault == "extra":
        proof["allow_dispatch"] = True
    elif fault == "remaining":
        kwargs["require_remaining"] = True
    elif fault == "exhausted":
        kwargs["require_exhausted"] = True
    with pytest.raises(ValueError):
        bound(terminal, **kwargs)
