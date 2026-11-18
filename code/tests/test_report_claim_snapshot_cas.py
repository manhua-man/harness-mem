"""Initial hash capture must reject a concurrent payload, not adopt its SHA."""
from __future__ import annotations

import json
import sys

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage
from test_terminal_source_coverage import terminal as terminal
from test_terminal_report_carrier_integration import report_terminal as report_terminal
from test_terminal_report_continuation import prepared as prepared, claim
from harness_mem.commands import dream_source_coverage


@pytest.mark.parametrize("target", ["origin", "child"])
def test_report_initial_hash_capture_cannot_overwrite_newer_payload(prepared, monkeypatch, target):
    data, child = prepared
    backend, _root, origin, *_rest = data[0]
    canonical = backend.structured_store._canonical
    identity = origin.id if target == "origin" else child.id
    original_get = canonical.get_payload_json
    changed = []

    def race(collection, entity_id, **kwargs):
        if (not changed and collection == "dream_runs" and entity_id == identity
                and sys._getframe(1).f_code.co_name == "claim_report_slice"):
            payload = json.loads(original_get(collection, entity_id, **kwargs))
            payload["notes"] = list(payload.get("notes") or []) + ["Concurrent capture-window update."]
            canonical.apply_payload_transaction(idempotency_key="fixture-report-initial-race-" + target,
                mutations=[{"operation": "upsert", "collection": collection,
                            "entity_id": entity_id, "payload": payload}])
            changed.append(payload)
        return original_get(collection, entity_id, **kwargs)

    monkeypatch.setattr(canonical, "get_payload_json", race)
    with pytest.raises(ValueError, match="terminal_report_initial_snapshot_changed"):
        claim(prepared)
    assert changed and json.loads(original_get("dream_runs", identity)) == changed[0]
    saved_origin = json.loads(original_get("dream_runs", origin.id))
    assert "terminal_coverage_takeover" not in saved_origin["continuation"]


@pytest.mark.parametrize("target", ["origin", "child"])
def test_source_initial_hash_capture_cannot_overwrite_newer_payload(terminal, monkeypatch, target):
    import asyncio
    backend, root, origin, carrier, _job, provider, config, _bindings = terminal
    canonical = backend.structured_store._canonical
    identity = origin.id if target == "origin" else carrier.id
    original_get = canonical.get_payload_json
    changed = []

    def race(collection, entity_id, **kwargs):
        if (not changed and collection == "dream_runs" and entity_id == identity
                and sys._getframe(1).f_code.co_name == "run_pending_terminal_source_coverage"):
            payload = json.loads(original_get(collection, entity_id, **kwargs))
            payload["notes"] = list(payload.get("notes") or []) + ["Concurrent source-capture update."]
            canonical.apply_payload_transaction(idempotency_key="fixture-source-initial-race-" + target,
                mutations=[{"operation": "upsert", "collection": collection,
                            "entity_id": entity_id, "payload": payload}])
            changed.append(payload)
        return original_get(collection, entity_id, **kwargs)

    monkeypatch.setattr(canonical, "get_payload_json", race)
    result = asyncio.run(dream_source_coverage.run_pending_terminal_source_coverage(
        backend, project_name="demo", project_root=root, carrier_run_id=carrier.id,
        provider=provider, config=config, host_client="codex"))
    assert result["status"] == "blocked" and "snapshot_changed" in result["reason"], result
    assert changed and json.loads(original_get("dream_runs", identity)) == changed[0]
    assert provider.calls == []
