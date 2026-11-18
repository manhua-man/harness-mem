"""Detached worker import identity; subprocess probes never run a host entry."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from harness_mem import hook_background as background


def request(root):
    return background.BackgroundRequest(generation="original-generation", project_root=str(root),
        client="codex", source="ide_hook", trigger_id="original-session", requested_at=0,
        resume_run_id="original-failed-run")


def capture(req):
    calls = []
    background._spawn_worker(req, popen=lambda command, **kwargs: calls.append((command, kwargs)))
    assert len(calls) == 1
    return calls[0]


def package(root, *, malicious=False):
    target = root / "harness_mem"
    target.mkdir(parents=True)
    body = "raise AssertionError('untrusted package loaded')\n" if malicious else "ORIGIN = 'parent runtime'\n"
    (target / "__init__.py").write_text(body, encoding="utf-8")
    (target / "hook_background.py").write_text("# owner identity fixture\n", encoding="utf-8")
    return target


@pytest.mark.parametrize("parent_kind", ["source checkout", "installed runtime"])
@pytest.mark.parametrize("inject", ["cwd", "pythonpath", "both"])
def test_child_import_pins_parent_and_ignores_workspace_and_pythonpath(tmp_path, monkeypatch, parent_kind, inject):
    owner = tmp_path / parent_kind
    parent_package = package(owner)
    workspace = tmp_path / "untrusted workspace"
    workspace.mkdir()
    injection = tmp_path / "untrusted Python path"
    injection.mkdir()
    if inject in {"cwd", "both"}:
        package(workspace, malicious=True)
    if inject in {"pythonpath", "both"}:
        package(injection, malicious=True)
    monkeypatch.setattr(background, "__file__", str(parent_package / "hook_background.py"))
    monkeypatch.setenv("PYTHONPATH", str(injection))
    command, options = capture(request(workspace))
    assert command[:3] == [sys.executable, "-I", "-c"]
    assert command[4] == str(owner.resolve())
    # Execute the generated isolation and path bootstrap, replacing only the
    # entry dispatch with an import-origin print. No Hook or worker can run.
    dispatch = "runpy.run_module('harness_mem.host_entry.__main__',run_name='__main__')"
    assert command[3].endswith(dispatch)
    probe = command.copy()
    probe[3] = command[3].replace(dispatch,
        "import harness_mem,json;print(json.dumps({'file':harness_mem.__file__,'origin':harness_mem.ORIGIN}))")
    result = subprocess.run(probe, cwd=options["cwd"], env=options["env"],
        capture_output=True, text=True, check=True, timeout=10)
    observed = json.loads(result.stdout)
    assert Path(observed["file"]).resolve() == (parent_package / "__init__.py").resolve()
    assert observed["origin"] == "parent runtime"


def test_spawn_preserves_original_flags_lease_environment_and_hidden_window(tmp_path, monkeypatch):
    monkeypatch.setattr(background, "diagnostic_parent_id", lambda: "original-parent")
    monkeypatch.setenv("HARNESS_MEM_TEST_PRESERVED", "caller-value")
    req = request(tmp_path)
    command, options = capture(req)
    assert command[4] == str(Path(background.__file__).resolve().parents[1])
    assert command[5:] == ["--action", "post-turn-maintenance", "--project-root", str(tmp_path),
        "--source", "ide_hook", "--client", "codex", "--trigger-id", "original-session"]
    assert "--resume-run-id" not in command  # Existing immutable queue owns it.
    assert options["env"][background.BACKGROUND_WORKER_ENV] == "1"
    assert options["env"][background._BACKGROUND_GENERATION_ENV] == req.generation
    assert options["env"][background._BACKGROUND_LEASE_ENV] == req.generation
    assert options["env"][background._DEBUG_PARENT_ENV] == "original-parent"
    assert options["env"]["HARNESS_MEM_TEST_PRESERVED"] == "caller-value"
    assert options["cwd"] == str(tmp_path)
    assert options["stdin"] == options["stdout"] == options["stderr"] == subprocess.DEVNULL
    assert options["close_fds"] is True
    if os.name == "nt":
        assert options["creationflags"] == subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        assert options["start_new_session"] is True


def test_real_parent_source_import_remains_source_without_running_entry(tmp_path):
    command, options = capture(request(tmp_path))
    dispatch = "runpy.run_module('harness_mem.host_entry.__main__',run_name='__main__')"
    command[3] = command[3].replace(dispatch,
        "import harness_mem;print(harness_mem.__file__)")
    result = subprocess.run(command, cwd=options["cwd"], env=options["env"],
        capture_output=True, text=True, check=True, timeout=10)
    assert Path(result.stdout.strip()).resolve().parent == Path(background.__file__).resolve().parent


def test_real_queue_retains_original_pointer_and_coalesces(tmp_path):
    data = tmp_path / "isolated-data"
    calls = []
    kwargs = dict(project_root=tmp_path, client="codex", trigger_id="original-session",
        generation="original-generation", resume_run_id="original-failed-run",
        popen=lambda command, **options: calls.append((command, options)))
    first = background.dispatch_bound_continuation(data, **kwargs)
    second = background.dispatch_bound_continuation(data, **kwargs)
    assert first.spawned and second.coalesced and len(calls) == 1
    queued = background.load_background_request(data, project_root=tmp_path, client="codex",
        ready_only=True, now=0)
    assert queued.resume_run_id == "original-failed-run"
    assert queued.generation == "original-generation" and queued.trigger_id == "original-session"
    assert calls[0][0][:3] == [sys.executable, "-I", "-c"]
