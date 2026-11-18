"""A pre-transport refusal must not inherit the previous paid call identity."""
from __future__ import annotations

import json

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage, CoverageProvider, _cover, run
from harness_mem.autonomous.provider import ProviderError


class PredispatchRefusal(CoverageProvider):
    def __init__(self):
        super().__init__()
        self._last_budget_call_id = "previous-successful-paid-call"
        self.error = ProviderError(
            "Private request text is not a receipt", kind="unrecoverable",
            failure_reason="input_budget_exhausted",
        )

    def decide(self, manifest, **kwargs):
        self.calls.append("refused_before_transport")
        raise self.error


def test_predispatch_refusal_retains_absent_id_after_a_previous_success(coverage):
    backend, _root, _job, _entry, item, checkpoint, notes = coverage
    provider = PredispatchRefusal()
    before = [v.to_dict() for v in run(backend.structured_store.knowledge_store.list_entries("demo"))]
    with pytest.raises(ProviderError) as raised:
        run(_cover(coverage, provider))
    assert raised.value is provider.error and raised.value.__cause__ is None
    receipts = [json.loads(n.split(": ", 1)[1]) for n in notes
                if n.startswith("dream source coverage receipt: ")]
    assert len(receipts) == 1
    assert receipts[0]["phase"] == "provider_failure"
    assert receipts[0]["budget_call_id"] is None
    assert receipts[0]["attempt_results"] == receipts[0]["native_attempts"] == []
    assert "Private request text" not in json.dumps(receipts)
    assert checkpoint["source_coverage"][item.source_id]["reason_code"] == "input_budget_exhausted"
    assert provider.calls == ["refused_before_transport"]
    assert [v.to_dict() for v in run(backend.structured_store.knowledge_store.list_entries("demo"))] == before


def test_predispatch_refusal_cannot_attach_previous_success_id(coverage, monkeypatch):
    from harness_mem.autonomous import worker

    provider = PredispatchRefusal()
    original = worker.run_source_coverage_attempt

    def corrupt(*args, save, **kwargs):
        def changed(update):
            if "_provider_error" in update:
                update["_receipt"]["budget_call_id"] = provider._last_budget_call_id
            save(update)
        return original(*args, save=changed, **kwargs)

    monkeypatch.setattr(worker, "run_source_coverage_attempt", corrupt)
    with pytest.raises(ProviderError) as raised:
        run(_cover(coverage, provider))
    assert raised.value is provider.error
    assert str(raised.value.__cause__) == "source_coverage_failure_receipt_changed"
    assert not any(n.startswith("dream source coverage receipt: ") for n in coverage[-1])
    assert provider.calls == ["refused_before_transport"]
