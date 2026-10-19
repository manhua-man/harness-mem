"""Joint calls retain complete point coverage and isolate an invalid point."""
from pathlib import Path
import pytest

from harness_mem.autonomous.models import AssimilationDecision
from harness_mem.autonomous.provider import ProviderError, ProviderResult
from harness_mem.autonomous.worker import _assimilate_prepared_in_bounded_batches
from harness_mem.autonomous.worker import _sum_provider_metric
from harness_mem.commands.separated_assimilation import (
    SeparatedPreparedAssimilation,
    validate_separated_assimilation_decision,
)


@pytest.mark.parametrize("transient", [False, True])
def test_invalid_joint_batch_falls_back_without_losing_the_valid_point(tmp_path: Path, transient):
    prepared = SeparatedPreparedAssimilation(
        project_name="Cedar", project_root=str(tmp_path),
        candidate_ids=("permission", "unknown"),
        eligible_candidate_ids=("permission", "unknown"), automatic_points=(),
        answer_status_by_candidate={"permission": "ANSWERED", "unknown": "ANSWERED"},
        truth_by_handle={},
        manifest={
            "verified_candidates": [
                {"candidate_id": "permission", "statement": "Cedar allows optional audit exports."},
                {"candidate_id": "unknown", "statement": "Cedar archive period remains undecided."},
            ],
            "current_truth": [],
            "prior_batch_knowledge": [{"candidate_id": "earlier", "title": "Earlier result",
                                       "statement": "Cedar keeps original records.", "topic_path": ["storage"]}],
        },
    )

    class Provider:
        name = "invalid-joint-control"

        def __init__(self):
            self.calls = []

        def assimilate(self, manifest, *, runtime_dir, heartbeat=None):
            ids = [item["candidate_id"] for item in manifest["verified_candidates"]]
            self.calls.append(ids)
            assert manifest["prior_batch_knowledge"][0]["candidate_id"] == "earlier"
            if transient and ids == ["unknown"]:
                raise ProviderError("temporary transport failure", kind="transient")
            points = []
            if "permission" in ids:
                points.append({"candidate_id": "permission", "disposition": "add", "reason": "The verified permission remains future useful.",
                    "knowledge_items": [{"title": "Optional audit exports", "statement": "Cedar allows optional audit exports.",
                                         "topic_path": ["exports"], "claim_kind": "design_requirement"}]})
            # The bad point is deliberately omitted, never silently accepted.
            return ProviderResult(
                decision=AssimilationDecision.model_validate({"points": points}), provider=self.name,
                model="offline-control", duration_seconds=.01, input_sha256="a"*64,
                response_sha256="b"*64, input_tokens=10, output_tokens=10, total_tokens=20,
                event_count=1,
            )

    provider = Provider()
    if transient:
        with pytest.raises(ProviderError) as failure:
            _assimilate_prepared_in_bounded_batches(provider, prepared=prepared,
                                                    runtime_dir=tmp_path, heartbeat=None)
        error = failure.value
        assert error.kind == "transient"
        assert len(provider.calls) == 5
        assert len(error.attempt_results) == 4
        assert sum(item.attempt_count for item in error.attempt_results) + error.unknown_attempt_count == 5
        assert sum(item.total_tokens for item in error.attempt_results) == 80
        assert error.unknown_attempt_count == 1
        return
    result = _assimilate_prepared_in_bounded_batches(provider, prepared=prepared,
                                                     runtime_dir=tmp_path, heartbeat=None)
    assert provider.calls == [["permission", "unknown"]]*3 + [["permission"]] + [["unknown"]]*3
    assert result.attempt_count == len(provider.calls) == 7
    assert result.input_tokens == result.output_tokens == 70
    assert result.total_tokens == 140
    assert abs(result.duration_seconds - .07) < 1e-9
    assert result.event_count == 7
    assert [(point.candidate_id, point.disposition) for point in result.decision.points] == [
        ("permission", "add"), ("unknown", "defer"),
    ]
    plan = validate_separated_assimilation_decision(prepared, result.decision)
    assert plan["candidate_ids"] == ["permission", "unknown"]
    assert plan["point_count"] == 2
    assert plan["points"][0]["knowledge_items"][0]["statement"] == "Cedar allows optional audit exports."
    assert not plan["points"][1]["knowledge_items"]


def test_missing_usage_is_not_treated_as_a_zero_cost_attempt():
    assert _sum_provider_metric(12, None) is None
    assert _sum_provider_metric(None, 12) is None
    assert _sum_provider_metric(None, None) is None
    assert _sum_provider_metric(12, 0) == 12


@pytest.mark.parametrize('message', [
    'Conflicting duplicate native usage', 'unexpected native server request',
    'unexpected tool activity', 'invalid assimilation JSON: protocol failure is not schema authorization',
])
def test_fatal_protocol_failure_never_recurses_into_singleton_semantic_calls(tmp_path, message):
    prepared = SeparatedPreparedAssimilation(project_name='fixture', project_root=str(tmp_path),
        candidate_ids=('a', 'b'), eligible_candidate_ids=('a', 'b'), automatic_points=(),
        answer_status_by_candidate={'a': 'ANSWERED', 'b': 'ANSWERED'}, truth_by_handle={},
        manifest={'verified_candidates': [{'candidate_id': key, 'statement': 'A scoped verified choice.'}
                    for key in ('a', 'b')], 'current_truth': []})
    calls = []
    class Provider:
        name = 'fatal-protocol-fixture'
        def assimilate(self, manifest, **_kwargs):
            calls.append(manifest)
            raise ProviderError(message, kind='unrecoverable')
    with pytest.raises(ProviderError) as failure:
        _assimilate_prepared_in_bounded_batches(Provider(), prepared=prepared,
            runtime_dir=tmp_path, heartbeat=None)
    assert str(failure.value) == message
    assert failure.value.failure_reason is None
    assert len(calls) == 1
