"""Loop harness scenario 4 — supersede actually replaces current truth.

Question answered: "after a user confirms a supersede candidate, does
default search/list return only the new truth, while ``include_history``
still surfaces the old truth for audit?"

This stresses the v1.7.1 supersede loop end-to-end (周明远 P1 痛点):
schema upgrades and policy reversals create exactly this situation, and
if the old rule is still surfaced by default after replacement the user's
mental model collapses ("did harness-mem really learn the new thing or
not?").

Note this scenario does *not* exercise CLI / MCP supersede surfaces — it
goes straight to the structured_store. That gap (no CLI path through
supersede end-to-end) is the next concrete fix the 周明远 user-card
flagged. Add a CLI-level scenario here once that lands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.core.schemas import ConfirmedRule, SupersedeCandidate
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run
from tests.loop_harness.conftest import LoopMetrics

pytestmark = pytest.mark.loop_harness


def test_confirm_supersede_replaces_default_truth(data_dir: Path):
    project_name = "loop-harness-supersede"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        store = backend.structured_store

        old_rule = ConfirmedRule(
            id="rule-tauri-v1",
            project_name=project_name,
            trigger="Before changing Tauri IPC code on Windows",
            pattern=(
                "On Windows, prefer Tauri invoke over emit for any IPC "
                "payload larger than ~1MB. (Tauri v1.x)"
            ),
            source_candidate_id="seed-old",
        )
        new_rule = ConfirmedRule(
            id="rule-tauri-v2",
            project_name=project_name,
            trigger="Before changing Tauri IPC code on Windows",
            pattern=(
                "Tauri v2 channels resolve the large-payload deadlock; use "
                "tauri::ipc::Channel<T> for streaming and reserve invoke "
                "for request/response."
            ),
            source_candidate_id="seed-new",
        )
        run(store.save_confirmed_rule(old_rule))
        run(store.save_confirmed_rule(new_rule))

        candidate = SupersedeCandidate(
            id="sup-tauri-v1-to-v2",
            project_name=project_name,
            target_type="confirmed_rule",
            target_id=old_rule.id,
            replacement_type="confirmed_rule",
            replacement_id=new_rule.id,
            reason="Tauri v2 channels obsolete the v1 emit/invoke threshold rule.",
            evidence=(
                "After the v2 upgrade, the document tree streams cleanly "
                "via tauri::ipc::Channel without the v1 deadlock."
            ),
            source="manual",
        )
        run(store.save_supersede_candidate(candidate))

        # Pre-condition: both rules visible by default before confirmation.
        before = run(store.list_confirmed_rules(project_name))
        before_ids = {rule.id for rule in before}
        assert before_ids == {old_rule.id, new_rule.id}

        confirmed = run(store.confirm_supersede_candidate(candidate.id))
        assert confirmed is not None
        assert confirmed.status == "accepted"

        # Post-condition 1: default list returns only the new rule.
        current = run(store.list_confirmed_rules(project_name))
        current_ids = {rule.id for rule in current}
        current_truth_correct = current_ids == {new_rule.id}

        # Post-condition 2: include_history=True still surfaces the old rule
        # so audits and timeline queries can find it.
        with_history = run(
            store.list_confirmed_rules(project_name, include_history=True)
        )
        history_ids = {rule.id for rule in with_history}
        history_visible = old_rule.id in history_ids and new_rule.id in history_ids

        # Post-condition 3: old rule has valid_to set + superseded_by link.
        old_loaded = run(store.get_confirmed_rule(old_rule.id))
        new_loaded = run(store.get_confirmed_rule(new_rule.id))
        assert old_loaded is not None and new_loaded is not None
        link_intact = (
            old_loaded.valid_to is not None
            and old_loaded.superseded_by == [new_rule.id]
            and new_loaded.supersedes == [old_rule.id]
        )

        LoopMetrics(
            name="supersede_replaces",
            values={
                "current_truth_correct": float(current_truth_correct),
                "history_visible_when_requested": float(history_visible),
                "link_intact": float(link_intact),
            },
        ).report()

        assert current_truth_correct, (
            f"Default list_confirmed_rules should return only the replacement "
            f"after supersede; got {current_ids}"
        )
        assert history_visible, (
            "include_history=True should surface both old and replacement "
            f"rules; got {history_ids}"
        )
        assert link_intact, (
            "Supersede link is broken: "
            f"old.valid_to={old_loaded.valid_to}, "
            f"old.superseded_by={old_loaded.superseded_by}, "
            f"new.supersedes={new_loaded.supersedes}"
        )
    finally:
        run(backend.close())
