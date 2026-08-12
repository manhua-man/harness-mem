from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness_mem.autonomous.models import AutonomousDecision
from harness_mem.autonomous.provider import (
    DEFAULT_DISTILL_TIMEOUT_SECONDS,
    ResponsesApiProvider,
    _build_prompt,
    _strict_output_schema,
)


def test_responses_provider_default_timeout_matches_product_gate() -> None:
    provider = ResponsesApiProvider()
    assert provider.timeout_seconds == DEFAULT_DISTILL_TIMEOUT_SECONDS
    assert provider.model == "gpt-5.6-luna"


def test_provider_prompt_requires_user_statement_evidence_basis() -> None:
    prompt = _build_prompt({"coverage": "complete"})
    assert "must use evidence_basis=user_statement" in prompt
    assert "Never label direct user evidence as transcript" in prompt


def _decision() -> AutonomousDecision:
    return AutonomousDecision.model_validate(
        {
            "semantic_review": {
                "session_summary": "The session only reported a transient status update.",
                "final_user_request": "Report the current status.",
                "final_outcome": "The status was reported without a durable decision.",
                "last_turn_status": "answered",
                "contradictions": [],
                "unfinished_work": [],
                "evidence_status": "answered",
                "promotion_decision": "no_promotion",
                "zero_candidate_challenge": {
                    "version": "v1",
                    "source_revision": "sha256:" + "a" * 64,
                    "evidence_fidelity": "complete",
                    "future_utility": "none",
                    "checks": {
                        "user_correction": "absent",
                        "explicit_decision": "absent",
                        "successful_solution": "not_durable",
                        "repeated_failure": "absent",
                        "rule_or_preference": "absent",
                        "reusable_workflow_or_fact": "absent",
                        "version_or_migration": "absent",
                        "unfinished_handoff": "absent",
                    },
                    "inspected_exchange_refs": [
                        {"exchange_index": 1, "content_sha256": "b" * 64}
                    ],
                    "conclusion": "no_durable_candidate",
                    "rationale": "successful_solution is session-only because no reusable implementation evidence was provided.",
                },
            },
            "candidates": [],
        }
    )


def test_strict_schema_requires_every_object_property_and_avoids_one_of() -> None:
    schema = _strict_output_schema(AutonomousDecision.model_json_schema())

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            assert "oneOf" not in value
            assert "title" not in value
            assert "description" not in value
            if isinstance(value.get("properties"), dict):
                assert set(value["required"]) == set(value["properties"])
                assert value["additionalProperties"] is False
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(schema)


def test_responses_provider_uses_no_tools_and_records_actual_usage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        'model = "gpt-test"\n'
        'model_provider = "local"\n'
        '[model_providers.local]\n'
        'name = "Local"\n'
        'base_url = "http://127.0.0.1:9999/v1"\n'
        'wire_api = "responses"\n'
        'requires_openai_auth = false\n'
        'experimental_bearer_token = "secret-test-token"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    captured: dict[str, Any] = {}
    response_payload = {
        "model": "gpt-test",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": _decision().model_dump_json(),
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 1234, "output_tokens": 321, "total_tokens": 1555},
    }

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(response_payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = ResponsesApiProvider(timeout_seconds=60).decide(
        {
            "contract_version": "autonomous-distill-manifest-v1",
            "coverage": "complete_indexed_semantic_projection",
        },
        runtime_dir=tmp_path / "unused",
    )

    assert captured["url"] == "http://127.0.0.1:9999/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer secret-test-token"
    assert captured["body"]["tools"] == []
    assert captured["body"]["store"] is False
    assert captured["body"]["text"]["format"]["strict"] is True
    assert captured["body"]["reasoning"]["effort"] == "low"
    assert result.total_tokens == 1555
    assert result.sandbox == "no-tools"
