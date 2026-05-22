"""Loop harness scenario 8 — one-shot rule correction via supersede chain.

Question answered: "when reality changes (Tauri v1 -> v2, framework
upgrade, policy reversal), can a user replace an old confirmed rule
with a new one in a single action — without manually walking the
candidate -> confirm -> supersede-suggest -> supersede-confirm chain?"

This closes the 周明远 P1 痛点that the 1st/2nd audit flagged: the
supersede storage path was already wired (scenario 4 proves it), but
the *daily user entry point* — `harness-mem correct` and the matching
MCP tool — used to drop users on the candidate layer with no awareness
that an existing rule was being replaced. They had to:

  1. harness-mem correct ...           (creates RuleCandidate, status=pending)
  2. harness-mem confirm-rule <new>    (promotes to ConfirmedRule)
  3. harness-mem supersede ...         (creates SupersedeCandidate)
  4. harness-mem confirm-supersede ... (applies the temporal updates)

This scenario covers the new one-shot path:

  CLI:  harness-mem correct ... --supersedes <old_rule_id> --reason "Tauri v2"
  MCP:  suggest_correction(supersedes_rule_id=..., pattern=..., trigger=..., reason=...)

Both end states must be identical: old rule has valid_to set + superseded_by
link; new rule is current with supersedes link; the default
list_confirmed_rules returns only the new rule; include_history=True
still surfaces the old rule for audit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.commands.candidates import cmd_correct
from harness_mem.core.schemas import ConfirmedRule, Observation
from harness_mem.mcp.server import handle_request, set_backend_override
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run
from tests.loop_harness.conftest import LoopMetrics

pytestmark = pytest.mark.loop_harness


def _seed_old_rule(
    backend: LocalMemoryBackend, project_name: str, *, rule_id: str
) -> ConfirmedRule:
    rule = ConfirmedRule(
        id=rule_id,
        project_name=project_name,
        trigger="Before changing Tauri IPC code on Windows",
        pattern=(
            "On Windows, prefer Tauri invoke over emit for any IPC payload "
            "larger than ~1MB. (Tauri v1.x)"
        ),
        source_candidate_id="seed-old-tauri-v1",
    )
    run(backend.structured_store.save_confirmed_rule(rule))
    return rule


def _seed_correction_session(
    backend: LocalMemoryBackend, project_name: str, *, session_id: str
) -> None:
    """cmd_correct verifies session observations exist; seed one."""
    observation = Observation(
        session_id=session_id,
        client="claude-code",
        raw_content="Upgraded Tauri to v2, the v1 IPC rule is now wrong.",
        content_type="transcript",
        metadata={"project_name": project_name},
        tags=["session", "correction"],
    )
    run(backend.verbatim_store.save(observation))


def _assert_supersede_chain_intact(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    old_rule_id: str,
    new_pattern_fragment: str,
) -> None:
    current = run(backend.structured_store.list_confirmed_rules(project_name))
    current_ids = [rule.id for rule in current]
    assert old_rule_id not in current_ids, (
        f"old rule still surfaces by default after correction; current={current_ids}"
    )
    assert any(new_pattern_fragment in rule.pattern for rule in current), (
        f"new rule not present in default listing; got {[r.pattern for r in current]}"
    )

    with_history = run(
        backend.structured_store.list_confirmed_rules(project_name, include_history=True)
    )
    history_ids = {rule.id for rule in with_history}
    assert old_rule_id in history_ids, (
        f"include_history=True missing old rule; got {history_ids}"
    )

    old_loaded = run(backend.structured_store.get_confirmed_rule(old_rule_id))
    assert old_loaded is not None
    assert old_loaded.valid_to is not None, "old rule valid_to not set"
    assert old_loaded.superseded_by, "old rule missing superseded_by link"

    new_id = old_loaded.superseded_by[0]
    new_loaded = run(backend.structured_store.get_confirmed_rule(new_id))
    assert new_loaded is not None
    assert new_loaded.supersedes == [old_rule_id], (
        f"new rule supersedes link wrong; got {new_loaded.supersedes}"
    )


def test_cli_correct_with_supersedes_replaces_rule_in_one_step(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    """harness-mem correct ... --supersedes <id> applies the supersede chain."""
    project_name = "loop-harness-correct-supersede-cli"
    session_id = "tauri-v2-upgrade-session"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        old_rule = _seed_old_rule(backend, project_name, rule_id="rule-tauri-v1-cli")
        _seed_correction_session(backend, project_name, session_id=session_id)
    finally:
        run(backend.close())

    new_pattern = (
        "Tauri v2 channels resolve the large-payload deadlock; use "
        "tauri::ipc::Channel<T> for streaming and reserve invoke for "
        "request/response."
    )
    new_trigger = "Before changing Tauri IPC code on Windows (v2+)"

    exit_code = run(
        cmd_correct(
            session_id=session_id,
            project_name=project_name,
            pattern=new_pattern,
            trigger=new_trigger,
            supersedes_rule_id=old_rule.id,
            reason="Tauri v2 channels obsolete the v1 emit/invoke threshold rule.",
        )
    )
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Superseded rule" in captured
    assert old_rule.id in captured

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        _assert_supersede_chain_intact(
            backend,
            project_name=project_name,
            old_rule_id=old_rule.id,
            new_pattern_fragment="tauri::ipc::Channel",
        )
    finally:
        run(backend.close())


def test_mcp_suggest_correction_replaces_rule_in_one_step(
    data_dir: Path,
    backend: LocalMemoryBackend,
):
    """MCP suggest_correction tool returns the supersede chain ids."""
    project_name = "loop-harness-correct-supersede-mcp"
    old_rule = _seed_old_rule(backend, project_name, rule_id="rule-tauri-v1-mcp")

    set_backend_override(backend)
    try:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "suggest_correction",
                "arguments": {
                    "project_name": project_name,
                    "supersedes_rule_id": old_rule.id,
                    "pattern": (
                        "Tauri v2 channels resolve the large-payload deadlock; "
                        "use tauri::ipc::Channel<T> for streaming."
                    ),
                    "trigger": "Before changing Tauri IPC code on Windows (v2+)",
                    "reason": "Tauri v2 channels obsolete the v1 IPC rule.",
                    "source_session_id": "agent-tauri-v2-upgrade",
                },
            },
        }
        response = handle_request(request)
        assert response is not None
        assert "error" not in response

        import json
        payload = json.loads(response["result"]["content"][0]["text"])
        assert payload["success"] is True
        assert payload["old_rule_id"] == old_rule.id
        assert payload["new_rule_id"]
        assert payload["supersede_candidate_id"]
        assert payload["old_rule_valid_to"] is not None

        LoopMetrics(
            name="correction_one_shot_mcp",
            values={
                "old_rule_marked_historical": 1.0,
                "supersede_chain_returned": float(
                    bool(payload["supersede_candidate_id"]) and bool(payload["new_rule_id"])
                ),
            },
        ).report()

        _assert_supersede_chain_intact(
            backend,
            project_name=project_name,
            old_rule_id=old_rule.id,
            new_pattern_fragment="tauri::ipc::Channel",
        )
    finally:
        set_backend_override(None)


def test_mcp_suggest_correction_refuses_unknown_rule(
    data_dir: Path,
    backend: LocalMemoryBackend,
):
    """suggest_correction must fail loudly when the old rule doesn't exist."""
    set_backend_override(backend)
    try:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "suggest_correction",
                "arguments": {
                    "project_name": "loop-harness-correct-unknown",
                    "supersedes_rule_id": "nonexistent-rule-id",
                    "pattern": "irrelevant",
                    "trigger": "irrelevant",
                    "reason": "irrelevant",
                },
            },
        }
        response = handle_request(request)
        import json
        payload = json.loads(response["result"]["content"][0]["text"])
        assert payload["success"] is False
        assert "not found" in payload["error"].lower()
    finally:
        set_backend_override(None)


def test_mcp_suggest_correction_refuses_already_historical_rule(
    data_dir: Path,
    backend: LocalMemoryBackend,
):
    """suggest_correction must reject double-supersede attempts.

    Imagine a session re-runs an old correction script after the rule was
    already superseded — silently making a "supersede the historical rule"
    chain would corrupt the truth tree.
    """
    project_name = "loop-harness-correct-already-historical"
    old_rule = ConfirmedRule(
        id="rule-already-historical",
        project_name=project_name,
        trigger="trigger",
        pattern="pattern that is long enough.",
        source_candidate_id="seed",
        valid_to=datetime.now(timezone.utc),
    )
    run(backend.structured_store.save_confirmed_rule(old_rule))

    set_backend_override(backend)
    try:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "suggest_correction",
                "arguments": {
                    "project_name": project_name,
                    "supersedes_rule_id": old_rule.id,
                    "pattern": "new pattern",
                    "trigger": "new trigger",
                    "reason": "should fail",
                },
            },
        }
        response = handle_request(request)
        import json
        payload = json.loads(response["result"]["content"][0]["text"])
        assert payload["success"] is False
        assert "historical" in payload["error"].lower()
    finally:
        set_backend_override(None)
