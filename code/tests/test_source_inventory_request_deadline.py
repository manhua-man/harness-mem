"""Large source inventories reuse the existing bounded request-time mechanism."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from test_source_coverage_inventory_transport import fixture
from harness_mem.commands.dream_source_coverage import _CoverageProvider
from harness_mem.autonomous.executors.task_budget import task_budget_receipt_path
import json


@pytest.mark.parametrize("operation,contract,windows,original,remaining,raises,expected", [
    ("decide", None, 82, 300, 3600, False, 900),
    ("verify", "candidate-semantic-verification-v2", 82, 300, 617, False, 617),
    ("decide", None, 82, 300, 3600, True, 900),
    ("decide", None, 3, 300, 3600, False, 300),
    ("decide", None, 82, 60, 3600, False, 60),
    ("verify", "final-knowledge-scope-v1", 82, 300, 3600, False, 300),
    ("decide", None, 82, 300, 200, False, 300),
])
def test_inventory_deadline_stays_in_original_task_and_restores_provider(tmp_path, operation, contract, windows,
                                                                       original, remaining, raises, expected):
    manifest, _decision = fixture()
    source = manifest["source_coverage"]["inventory_input"]
    source["windows"] = source["windows"] * windows
    source["windows"] = source["windows"][:windows]
    if contract is not None:
        manifest["contract_version"] = contract
    scope = "maintenance:explicit-repair:generation"
    path = task_budget_receipt_path(tmp_path, scope)
    path.parent.mkdir(parents=True)
    raw = json.dumps({"schema_version": 1, "kind": "task_model_budget",
                      "bounds": {"max_seconds": remaining}, "calls": []}).encode()
    path.write_bytes(raw)
    provider = NS(timeout_seconds=original,
        task_budget_binding=NS(data_dir=tmp_path, task_scope=scope))
    seen = []
    def actual(incoming, **kwargs):
        assert incoming is manifest and kwargs == {"runtime_dir": tmp_path}
        seen.append(provider.timeout_seconds)
        if raises:
            raise RuntimeError("Retain the original failure")
        return "real-result"
    setattr(provider, operation, actual)
    wrapped = _CoverageProvider(provider, "source-coverage:run:binding")
    if raises:
        with pytest.raises(RuntimeError, match="Retain the original failure"):
            getattr(wrapped, operation)(manifest, runtime_dir=tmp_path)
    else:
        assert getattr(wrapped, operation)(manifest, runtime_dir=tmp_path) == "real-result"
    assert seen == [expected] and provider.timeout_seconds == original
    assert path.read_bytes() == raw and provider.task_budget_binding.task_scope == scope


@pytest.mark.parametrize("has_receipt,expected", [(False, 900), (True, 798)])
def test_first_call_and_known_consumption_use_same_budget_owner(tmp_path, has_receipt, expected):
    manifest, _decision = fixture()
    manifest["source_coverage"]["inventory_input"]["windows"] *= 30
    scope = "maintenance:new-production:shared-generation"
    path = task_budget_receipt_path(tmp_path, scope)
    raw = None
    if has_receipt:
        path.parent.mkdir(parents=True)
        raw = json.dumps({"schema_version": 1, "kind": "task_model_budget", "bounds": {"max_seconds": 1000},
            "calls": [{"usage_exact": True, "usage": {"input_tokens": 100, "output_tokens": 10,
                "duration_seconds": 201.1}}]}).encode()
        path.write_bytes(raw)
    provider = NS(timeout_seconds=300, task_budget_binding=NS(data_dir=tmp_path, task_scope=scope,
        config=NS(task_model_budget_max_seconds=3600)))
    provider.decide = lambda _manifest, **_: provider.timeout_seconds
    assert _CoverageProvider(provider, "source-coverage:run:binding").decide(manifest) == expected
    assert provider.timeout_seconds == 300
    assert path.read_bytes() == raw if has_receipt else not path.exists()
