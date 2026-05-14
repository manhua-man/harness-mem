from __future__ import annotations

import sys
from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.commands import profile as profile_mod
from harness_mem.commands import support as support_mod
from harness_mem.core.schemas import Observation
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run

pytestmark = pytest.mark.cli


def test_interactive_correct_via_main(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="session-correct-001",
                    client="claude-code",
                    raw_content="User corrected the agent to validate JWT expiry before authenticated calls.",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                    tags=["session", "correction"],
                )
            )
        )
    finally:
        run(backend.close())

    assert cli.cmd_use("demo") == 0
    answers = iter(
        [
            "session-correct-001",
            "Always validate JWT expiry before API calls",
            "Before any authenticated API call",
        ]
    )
    monkeypatch.setattr(cli, "_can_prompt", lambda: True)
    monkeypatch.setattr(support_mod, "can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr(sys, "argv", ["harness-mem", "correct"])

    assert cli.main() == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        candidates = run(backend.structured_store.list_rule_candidates("demo"))
        assert len(candidates) == 1
        assert candidates[0].pattern == "Always validate JWT expiry before API calls"
    finally:
        run(backend.close())


def test_interactive_handoff_via_main(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    assert cli.cmd_use("demo") == 0
    answers = iter(
        [
            "task-42",
            "Fix auth bug",
            "blocked",
            "Check JWT validation",
            "",
            "Waiting for token samples",
            "",
        ]
    )
    monkeypatch.setattr(cli, "_can_prompt", lambda: True)
    monkeypatch.setattr(support_mod, "can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr(sys, "argv", ["harness-mem", "handoff"])

    assert cli.main() == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        handoffs = run(backend.structured_store.get_latest_handoffs("demo", limit=10))
        assert len(handoffs) == 1
        assert handoffs[0].task_id == "task-42"
        assert handoffs[0].status == "blocked"
        assert handoffs[0].next_steps == ["Check JWT validation"]
        assert handoffs[0].blockers == ["Waiting for token samples"]
    finally:
        run(backend.close())


def test_handoff_cli_normalizes_status_and_strips_blank_list_items(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    assert cli.cmd_use("demo") == 0
    monkeypatch.setattr(cli, "_can_prompt", lambda: False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "harness-mem",
            "handoff",
            "-t",
            " task-42 ",
            "-s",
            " Fix auth bug ",
            "--status",
            "Blocked",
            "-n",
            " Check JWT validation ",
            "-n",
            "   ",
            "-b",
            " Waiting for token samples ",
        ],
    )

    assert cli.main() == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        handoffs = run(backend.structured_store.get_latest_handoffs("demo", limit=10))
        assert len(handoffs) == 1
        assert handoffs[0].task_id == "task-42"
        assert handoffs[0].summary == "Fix auth bug"
        assert handoffs[0].status == "blocked"
        assert handoffs[0].next_steps == ["Check JWT validation"]
        assert handoffs[0].blockers == ["Waiting for token samples"]
    finally:
        run(backend.close())


def test_correct_cli_rejects_conflicting_session_ids(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cli, "_can_prompt", lambda: False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "harness-mem",
            "correct",
            "session-a",
            "--session-id",
            "session-b",
            "-p",
            "demo",
            "-r",
            "Always validate JWT expiry before API calls",
            "-t",
            "Before any authenticated API call",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_handoff_cli_rejects_invalid_status(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cli, "_can_prompt", lambda: False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "harness-mem",
            "handoff",
            "-p",
            "demo",
            "-t",
            "task-42",
            "-s",
            "Fix auth bug",
            "--status",
            "paused",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_profile_edit_existing_profile_merges_without_crashing(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    profile_store = LocalProjectProfileStore(data_dir)
    run(
        profile_store.save(
            ProjectProfile(
                project_name="demo",
                description="old desc",
                stacks=["python"],
                key_files=["app.py"],
                conventions=["run tests first"],
            )
        )
    )

    answers = iter(["", "", "", ""])
    monkeypatch.setattr(cli, "_can_prompt", lambda: True)
    monkeypatch.setattr(profile_mod, "can_prompt", lambda: True)
    monkeypatch.setattr(support_mod, "can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert run(cli.cmd_profile_edit("demo")) == 0

    updated = run(profile_store.get("demo"))
    assert updated is not None
    assert updated.description == "old desc"
    assert updated.stacks == ["python"]
    assert updated.key_files == ["app.py"]
    assert updated.conventions == ["run tests first"]


def test_profile_edit_description_supports_clear(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    profile_store = LocalProjectProfileStore(data_dir)
    run(
        profile_store.save(
            ProjectProfile(
                project_name="demo",
                description="old desc",
                stacks=["python"],
                key_files=["app.py"],
                conventions=["run tests first"],
            )
        )
    )

    answers = iter(["!clear", "", "", ""])
    monkeypatch.setattr(cli, "_can_prompt", lambda: True)
    monkeypatch.setattr(profile_mod, "can_prompt", lambda: True)
    monkeypatch.setattr(support_mod, "can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert run(cli.cmd_profile_edit("demo")) == 0

    updated = run(profile_store.get("demo"))
    assert updated is not None
    assert updated.description == ""
