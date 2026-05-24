from __future__ import annotations

import sys
from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.commands import profile as profile_mod
from harness_mem.commands import support as support_mod
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run

pytestmark = pytest.mark.cli


@pytest.mark.parametrize(
    "command",
    [
        "use",
        "ingest",
        "wake",
        "wake-up",
        "search",
        "timeline",
        "status",
        "profile",
        "correct",
        "handoff",
        "candidates",
        "confirm",
        "reject",
        "rules",
        "api",
    ],
)
def test_daily_cli_commands_are_not_registered(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
):
    monkeypatch.setattr(sys, "argv", ["harness-mem", command])

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
    monkeypatch.setattr(profile_mod, "can_prompt", lambda: True)
    monkeypatch.setattr(support_mod, "can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert run(cli.cmd_profile_edit("demo")) == 0

    updated = run(profile_store.get("demo"))
    assert updated is not None
    assert updated.description == ""
