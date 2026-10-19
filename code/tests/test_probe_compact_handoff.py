from __future__ import annotations

from typing import Any

import pytest

from harness_mem.qualification import distill_outcome_probe as probe


def test_compact_finalize_is_proved_by_current_store_and_job_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finalize = probe.tool_handlers.tool_finalize_session_distill
    responses = []

    def compact_finalize(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = finalize(*args, **kwargs)
        assert "completion" not in result
        assert "handoff_ids" not in result
        responses.append(result)
        return result

    monkeypatch.setattr(probe.tool_handlers, "tool_finalize_session_distill", compact_finalize)
    result = probe.run_distill_outcome_probe()

    assert len(responses) == 1
    assert responses[0]["organization_status"] == "partial"
    assert result["partial_candidate_promoted"] is True
    assert result["handoff_job_bound"] is True
    assert result["verified"] is True


@pytest.mark.parametrize("missing", ["knowledge", "search", "job_readback", "handoff_binding"])
def test_legacy_public_receipt_cannot_hide_missing_direct_evidence(
    monkeypatch: pytest.MonkeyPatch, missing: str,
) -> None:
    finalize = probe.tool_handlers.tool_finalize_session_distill

    def damaged_readback(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = finalize(*args, **kwargs)
        backend = probe.tool_handlers._backend_provider()
        job = backend.transcript_store.get_distill_job(kwargs["job_id"])
        readback = dict(job.promotion_summary["readback"])
        # Even a reassuring legacy public response cannot replace direct proof.
        result["completion"] = {"disposition": "promoted"}
        result["handoff_ids"] = readback["handoff_ids"]
        if missing == "knowledge":
            async def no_entries(*args: Any, **kwargs: Any) -> list[Any]:
                return []
            monkeypatch.setattr(backend.structured_store.knowledge_store, "list_entries", no_entries)
        elif missing == "search":
            monkeypatch.setattr(probe.read_search_handlers, "tool_search_memory", lambda **kwargs: {"memories": []})
        elif missing == "job_readback":
            damaged = job.model_copy(update={"promotion_summary": {
                **job.promotion_summary,
                "readback": {**readback, "handoff_ids": ["another-handoff"]},
            }})
            monkeypatch.setattr(backend.transcript_store, "get_distill_job", lambda _: damaged)
        else:
            get_handoff = backend.structured_store.get_task_handoff

            async def unrelated_handoff(handoff_id: str) -> Any:
                handoff = await get_handoff(handoff_id)
                return handoff.model_copy(update={"context": {"distill_job_id": "another-job"}})
            monkeypatch.setattr(backend.structured_store, "get_task_handoff", unrelated_handoff)
        return result

    monkeypatch.setattr(probe.tool_handlers, "tool_finalize_session_distill", damaged_readback)
    result = probe.run_distill_outcome_probe()

    assert result["verified"] is False
    if missing in {"knowledge", "search"}:
        assert result["partial_candidate_promoted"] is False
    else:
        assert result["handoff_persisted"] is True
        assert result["handoff_job_bound"] is False
