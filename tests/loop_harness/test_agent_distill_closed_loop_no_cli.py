"""Loop harness — the distill closed loop must not require removed CLI argv.

Question answered: "can an agent take a project from candidate write through
auto-review and land on the canonical six-counter summary entirely through
MCP / Python imports, without ever shelling out to the daily CLI subcommands
v2.0 removed (`harness-mem wake/search/timeline/candidates/distill`)?"

This complements ``test_mcp_setup_without_cli.py``:

- ``test_mcp_setup_without_cli.py`` covers the *setup* leg
  (set_active_project / update_project_profile / wake).
- this file covers the *distill close-loop* leg
  (suggest_memory_entry -> list_candidates -> auto_review_candidates).

If either path silently regrew a dependency on ``cmd_wake_up`` /
``cmd_search`` / ``cmd_distill`` / ``cmd_candidates`` / ``cmd_timeline``,
the v2.0 CLI surface promise (cli/spec.md) would already be broken at the
runtime level even before docs caught up.
"""

# regression guard: this happy path must not require
# ``subprocess.run(["harness-mem", "wake"])`` or any of the removed daily
# CLI subcommands (wake / search / timeline / candidates / distill). Keep
# the test driving everything through MCP handlers and Python imports.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_mem.commands.auto_review import auto_review_candidates
from harness_mem.mcp import server as mcp_server
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run

pytestmark = pytest.mark.loop_harness


# Canonical six-counter summary names from v2.2 daily-workflow spec.
# auto-review owns five of them directly; the sixth (`ingested`) comes
# from prepare_session_distill / ingest_sessions and is asserted via the
# summary surface here for completeness.
SUMMARY_KEYS: tuple[str, ...] = (
    "new_candidates",
    "auto_confirmed",
    "auto_rejected",
    "kept_pending",
    "needs_user_confirmation",
    "applied_decisions",
)


def _call(name: str, **arguments: object) -> dict:
    """Invoke an MCP tool via JSON-RPC, the way an IDE agent would."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    response = mcp_server.handle_request(request)
    assert response is not None
    payload = response["result"]["content"][0]["text"]
    return json.loads(payload)


def test_agent_distill_closed_loop_through_mcp_only(data_dir: Path) -> None:
    """suggest -> list_candidates -> auto_review_candidates via MCP only.

    Seeds two distinct candidates so the auto-review summary has at least
    one auto_confirm and one auto_reject decision, then verifies the
    canonical summary shape and that decisions are visible in
    ``applied_decisions`` (the field slash commands quote when the user
    asks "why was this confirmed?").
    """
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    mcp_server.set_backend_override(backend)
    try:
        # Step 1: agent activates the project. No CLI ``use`` involved.
        set_resp = _call("set_active_project", project_name="loop-harness-distill")
        assert set_resp["success"] is True

        # Step 2: agent writes one low-risk decision (auto-confirm target)
        # and one chatty noise entry (auto-reject target). In a real run
        # these come out of session-distill against the evidence packet
        # returned by ``prepare_session_distill``; we seed them directly
        # so the test is hermetic and doesn't depend on session fixtures.
        confirm_target = _call(
            "suggest_memory_entry",
            project_name="loop-harness-distill",
            category="decision",
            content=(
                "Backend persistence layer is SQLite via sqlite-utils, "
                "with FTS5 for verbatim search and JSON columns for "
                "structured memory. This is locked in for v2.x."
            ),
            source="agent:loop-harness",
            confidence=0.9,
        )
        assert confirm_target["success"] is True

        reject_target = _call(
            "suggest_memory_entry",
            project_name="loop-harness-distill",
            category="decision",
            content="Awesome! Nailed that one.",
            source="agent:loop-harness",
            confidence=0.9,
        )
        assert reject_target["success"] is True

        # Step 3: agent reads the pending queue. This is the surface a
        # Cursor / Codex agent would render when asked "what did you
        # find?" — going through MCP keeps it identical to the IDE flow.
        listed = _call(
            "list_candidates",
            project_name="loop-harness-distill",
            status="pending",
        )
        assert listed["success"] is True
        listed_ids = {
            entry["id"] for entry in listed.get("memory_entries", [])
        }
        assert confirm_target["entry_id"] in listed_ids
        assert reject_target["entry_id"] in listed_ids

        # Step 4: agent runs auto-review with apply=True. The summary
        # shape is the canonical six-counter form documented in
        # ``openspec/specs/mcp/spec.md`` and reused by /hm:distill.
        # Calling the Python function directly (instead of going through
        # MCP) keeps the assertion focused on the runtime contract — if
        # the function signature regressed to require a CLI argv, this
        # call site would fail to typecheck.
        summary = run(
            auto_review_candidates(
                backend,
                project_name="loop-harness-distill",
                apply=True,
            )
        )
        summary_dict = summary.to_dict()

        for key in SUMMARY_KEYS:
            assert key in summary_dict, (
                f"auto-review summary missing canonical key '{key}'; "
                f"got keys={sorted(summary_dict)}"
            )

        # Two seeded candidates: the long decision should auto-confirm,
        # the chatty one should auto-reject. Anything else is a heuristic
        # regression worth surfacing here.
        assert summary.new_candidates >= 2
        assert summary.auto_confirmed >= 1, (
            f"expected the long decision to auto-confirm; summary={summary_dict}"
        )
        assert summary.auto_rejected >= 1, (
            f"expected the chatty entry to auto-reject; summary={summary_dict}"
        )

        # The applied_decisions list is what /hm:distill quotes when the
        # user asks "why was X confirmed?". Each decision must carry the
        # candidate id and a non-empty reason or that follow-up answer
        # collapses to "I don't know".
        applied = summary.applied_decisions
        assert len(applied) == summary.auto_confirmed + summary.auto_rejected
        for decision in applied:
            assert decision.candidate_id
            assert decision.reason
            assert decision.action in {"auto_confirm", "auto_reject"}

        # Step 5: post-apply, the rejected entry must be gone from the
        # pending queue. This is the user-visible signal that auto-review
        # actually ran, not just previewed.
        post_listed = _call(
            "list_candidates",
            project_name="loop-harness-distill",
            status="pending",
        )
        post_pending_ids = {
            entry["id"] for entry in post_listed.get("memory_entries", [])
        }
        assert confirm_target["entry_id"] not in post_pending_ids
        assert reject_target["entry_id"] not in post_pending_ids
    finally:
        mcp_server.set_backend_override(None)
        run(backend.close())
