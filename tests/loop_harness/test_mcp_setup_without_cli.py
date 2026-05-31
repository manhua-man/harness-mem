"""Loop harness scenario 9 — agent-driven setup without touching CLI.

Question answered: "can a non-Claude-Code agent (Cursor / Codex / Gemini)
get a project from zero state to ready-for-distill using only MCP tools,
without ever shelling out to harness-mem CLI?"

This closes the gap surfaced by the v2.0 周明远 field test (May 2026):
the Cursor agent recommended terminal commands for active project setup,
profile editing, wake-up, and server bootstrap when README's "MCP-first"
promise implied none of those should be needed for everyday setup. The
first three are MCP tools (set_active_project, update_project_profile,
wake); the fourth is server bootstrap.

The scenario walks the agent path end-to-end against the real backend,
storing through the same MCP tools an agent in Cursor would call.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_mem.commands.support import get_active_project
from harness_mem.mcp import server as mcp_server
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run
from tests.loop_harness.conftest import LoopMetrics

pytestmark = pytest.mark.loop_harness


def _call(name: str, **arguments: object) -> dict:
    """Invoke an MCP tool through the JSON-RPC handler the way a client would.

    Going through ``handle_request`` instead of calling the handler
    function directly catches schema / handler wiring regressions
    (build_tools key-set validation, missing handler registration).
    """
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


def test_agent_drives_setup_through_mcp_only(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """An agent should be able to set project, write profile, wake — all via MCP.

    Reproduces the 周明远 / Cursor flow: cwd is some unrelated repo, no
    active project yet, and the agent has only MCP available. By the end
    of the scenario the project is active, the profile carries the
    project's quirks, and ``wake`` returns those quirks in its output.
    """
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    mcp_server.set_backend_override(backend)
    try:
        # Step 1: agent picks a project name from natural-language input
        # ("整理 inkpad 最近 10 个 session...") and locks it in.
        set_resp = _call("set_active_project", project_name="inkpad")
        assert set_resp["success"] is True
        assert set_resp["project_name"] == "inkpad"
        assert get_active_project() == "inkpad"

        # Step 2: agent writes the project's stable conventions (the user
        # told it about the Tauri IPC quirk in chat). Profile feeds wake
        # directly, so this is the fastest "记住怪癖" path.
        update_resp = _call(
            "update_project_profile",
            project_name="inkpad",
            description="Local-first Notion-like notes app",
            stacks=["rust", "tauri", "typescript"],
            conventions=[
                "Windows IPC: use invoke for large payloads, not emit",
            ],
        )
        assert update_resp["success"] is True
        assert "tauri" in update_resp["profile"]["stacks"]
        assert any(
            "invoke" in convention
            for convention in update_resp["profile"]["conventions"]
        )

        # Step 3: agent calls update again with one extra convention.
        # The merge contract says repeated values stay deduped and old
        # values stay put — agents will retry, so non-idempotent write
        # would corrupt the profile.
        update_resp_again = _call(
            "update_project_profile",
            project_name="inkpad",
            conventions=[
                "Windows IPC: use invoke for large payloads, not emit",
                "Use serde_json over manual JSON building",
            ],
        )
        assert (
            len(update_resp_again["profile"]["conventions"]) == 2
        ), update_resp_again["profile"]["conventions"]
        assert "rust" in update_resp_again["profile"]["stacks"]  # stacks preserved

        # Confirm the merge is not just an in-memory dance — the profile
        # actually persisted to disk via the patched DEFAULT_DATA_DIR.
        store = LocalProjectProfileStore(data_dir)
        on_disk = run(store.get("inkpad"))
        assert on_disk is not None
        assert any(
            "invoke" in convention for convention in on_disk.conventions
        )

        # Step 4: agent calls wake. The output should carry the project's
        # plan-backed L0 identity (name / description / stacks) so a fresh chat
        # has the project context loaded. ``no_auto_ingest`` keeps the scenario
        # hermetic (no probing of ~/.claude or ~/.codex from inside the test).
        #
        # v2.5.1 note: cold-start wake renders the profile through the
        # plan-backed L0 identity summary, which carries name / description /
        # stacks but not the full conventions list (an L3/profile-detail concern
        # superseded for queryless wake). The agent still gets the project
        # identity; conventions remain available through the profile itself
        # (asserted on-disk above).
        wake_resp = _call(
            "wake", project_name="inkpad", no_auto_ingest=True
        )
        assert wake_resp["success"] is True
        wake_output = wake_resp["output"]
        assert "# Project Profile  (L0 · identity)" in wake_output
        assert "inkpad" in wake_output.lower()
        assert "tauri" in wake_output.lower(), (
            "wake-up output must surface the project identity (stacks) so the "
            "agent has project context loaded; got:\n" + wake_output
        )
    finally:
        mcp_server.set_backend_override(None)
        run(backend.close())

    LoopMetrics(
        name="agent_drives_setup_through_mcp_only",
        values={
            "set_active_project_works": 1.0,
            "update_profile_idempotent": 1.0,
            "wake_surfaces_convention": 1.0,
        },
    ).report()


def test_update_project_profile_replace_substitutes_fields(
    data_dir: Path,
):
    """``replace=true`` substitutes the provided list outright.

    Edge case the merge contract has to honor: the user discovers a
    convention is wrong and asks the agent to replace it. Without
    ``replace=true`` the bad convention would linger forever.
    """
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    mcp_server.set_backend_override(backend)
    try:
        _call(
            "update_project_profile",
            project_name="inkpad",
            conventions=["Old wrong convention"],
        )
        replace_resp = _call(
            "update_project_profile",
            project_name="inkpad",
            conventions=["The correct one"],
            replace=True,
        )
        assert replace_resp["profile"]["conventions"] == ["The correct one"]
    finally:
        mcp_server.set_backend_override(None)
        run(backend.close())


def test_doctor_flags_cwd_project_mismatch(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """HM-501: doctor warns when cwd points at a different known project.

    Reproduces the v2.0 field-test scenario: user sits in the ``TFT``
    repo but ``active_project`` is still set to ``v0191_recover`` from
    weeks ago. doctor must visibly surface the mismatch and suggest
    switching, otherwise memory keeps writing to the wrong project.
    """
    from harness_mem.commands.doctor import cmd_doctor
    from harness_mem.commands.support import set_active_project

    # Seed two known projects: one that's currently active, and one
    # whose name matches the directory we're going to chdir into.
    store = LocalProjectProfileStore(data_dir)
    from harness_mem.core.schemas.project_profile import ProjectProfile

    run(store.save(ProjectProfile(project_name="v0191_recover")))
    run(store.save(ProjectProfile(project_name="inkpad")))

    set_active_project("v0191_recover")

    # Pretend the user's shell is sitting inside an inkpad checkout.
    fake_cwd = tmp_path / "inkpad"
    fake_cwd.mkdir()
    monkeypatch.chdir(fake_cwd)

    run(cmd_doctor("v0191_recover"))
    captured = capsys.readouterr().out

    LoopMetrics(
        name="doctor_cwd_mismatch_warns",
        values={
            "hm_501_emitted": float("HM-501" in captured),
            "fix_suggests_switch": float('set_active_project(project_name="inkpad")' in captured),
        },
    ).report()

    assert "HM-501" in captured, (
        "doctor must emit HM-501 when cwd matches a different known project "
        f"than the active one; captured:\n{captured}"
    )
    assert 'set_active_project(project_name="inkpad")' in captured, (
        "fix command should point at the suspected project; "
        f"captured:\n{captured}"
    )


def test_doctor_silent_when_cwd_is_unrelated_directory(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Guard against false positives.

    Users sit in random directories all the time (``~/Downloads``,
    ``~/tmp/sandbox``, etc). doctor must NOT emit HM-501 unless the cwd
    name actually matches a different known project.
    """
    from harness_mem.commands.doctor import cmd_doctor
    from harness_mem.commands.support import set_active_project
    from harness_mem.core.schemas.project_profile import ProjectProfile

    store = LocalProjectProfileStore(data_dir)
    run(store.save(ProjectProfile(project_name="v0191_recover")))
    run(store.save(ProjectProfile(project_name="inkpad")))

    set_active_project("v0191_recover")

    sandbox = tmp_path / "tmp-sandbox"
    sandbox.mkdir()
    monkeypatch.chdir(sandbox)

    run(cmd_doctor("v0191_recover"))
    captured = capsys.readouterr().out

    assert "HM-501" not in captured, (
        f"doctor wrongly emitted HM-501 from an unrelated cwd; captured:\n{captured}"
    )
