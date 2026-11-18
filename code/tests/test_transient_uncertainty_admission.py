"""Prompt wiring only; actual semantic evidence comes from the retained native report."""
import pytest

from harness_mem.autonomous.provider import (
    DREAM_SOURCE_RECHECK_CONTRACT,
    _UNDECIDED_USE_CONTRACT,
    _build_assimilation_prompt,
    _build_prompt,
    _build_verification_prompt,
)


@pytest.mark.parametrize("stage", ["extract", "assimilate", "verify", "classify", "final"])
def test_common_prompts_distinguish_pending_reply_from_continuing_setting(stage):
    if stage == "extract":
        prompt = _build_prompt({"coverage": "complete"})
    elif stage == "assimilate":
        prompt = _build_assimilation_prompt({"verified_candidates": []})
    elif stage == "verify":
        prompt = _build_verification_prompt({"candidates": []})
    elif stage == "classify":
        prompt = _build_verification_prompt({"contract_version": DREAM_SOURCE_RECHECK_CONTRACT, "candidates": []})
    else:
        prompt = _build_verification_prompt(
            {"contract_version": "final-knowledge-scope-v1", "candidates": []},
            native_final_transport=True,
        )
    assert prompt.count(_UNDECIDED_USE_CONTRACT) == 1
    assert "independent use beyond completing the current intake, audit or reply" in prompt
    assert "Preserve that real setting's exact undecided status" in prompt
    assert "any still-applicable finite constraint" in prompt
    assert "Mentioning future use in the question is not that evidence" in prompt
    assert "An explicitly undecided setting is a durable known-unknown fact" not in prompt
