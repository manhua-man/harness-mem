"""Real local Codex-shaped processes distinguish parent exit from pipe EOF.

Minimal reproduction (no model or Hook):
    python -m pytest -q code/tests/test_host_cli_pipe_completion.py

Only command routing is replaced. Popen, communicate, timeout handling, leases,
return-code classification and decision validation all use the real runtime.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import time
from typing import Iterator

import pytest

from harness_mem.autonomous.executors import host_structured_cli
from harness_mem.autonomous.executors.host_structured_cli import HostStructuredCliProvider
from harness_mem.autonomous.models import AssimilationDecision
from harness_mem.autonomous.provider import ProviderError, ProviderResult


_LOCAL_CLI = r'''
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

mode, directory, *args = sys.argv[1:]
signals = Path(directory)
if mode == "child":
    # These are the parent's actual stdout/stderr handles, not replacement pipes.
    (signals / "child-ready.json").write_text(json.dumps({
        "stdout_pipe": stat.S_ISFIFO(os.fstat(1).st_mode),
        "stderr_pipe": stat.S_ISFIFO(os.fstat(2).st_mode),
        "pid": os.getpid(),
        "cwd": str(Path.cwd()),
    }), encoding="utf-8")
    deadline = time.monotonic() + 30
    while not (signals / "release-child").exists():
        if time.monotonic() >= deadline:
            sys.exit(99)
        time.sleep(0.01)
    (signals / "child-finished").touch()
    sys.exit(0)

def spawn_child():
    subprocess.Popen(
        [sys.executable, "-I", "-u", __file__, "child", str(signals)],
        stdin=subprocess.DEVNULL,
        stdout=sys.stdout,
        stderr=sys.stderr,
        cwd=Path.cwd(),
        close_fds=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    deadline = time.monotonic() + 5
    while not (signals / "child-ready.json").exists():
        if time.monotonic() >= deadline:
            sys.exit(98)
        time.sleep(0.01)

if mode.startswith("startup"):
    spawn_child()  # Intentionally before reading stdin: containment must precede startup.
prompt = sys.stdin.read()
(signals / "stdin.txt").write_text(prompt, encoding="utf-8")
payload = {"points": []} if mode != "invalid" else {"points": "invalid"}
raw = json.dumps(payload)
output = None
for flag in ("--output-last-message", "--output"):
    if flag in args:
        output = Path(args[args.index(flag) + 1])
        output.write_text(raw, encoding="utf-8")
        break
# Retain an independent test witness after runtime scratch-directory cleanup.
(signals / "decision.json").write_text(raw, encoding="utf-8")
if output is None:
    print(json.dumps({"structured_output": payload}), flush=True)
else:
    print(json.dumps({"usage": {
        "input_tokens": 100, "output_tokens": 25, "total_tokens": 125,
    }}), flush=True)
print("local CLI diagnostic", file=sys.stderr, flush=True)

if mode.endswith("timeout"):
    (signals / "parent-running").touch()
    (signals / "parent-ready.json").write_text(json.dumps({"pid": os.getpid()}))
    time.sleep(30)
elif not mode.startswith("startup"):
    spawn_child()
(signals / "parent-exiting").touch()
if mode == "nonzero":
    print("authentication denied by local fixture", file=sys.stderr, flush=True)
    sys.exit(7)
'''


def _wait_for(path: Path, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            pytest.fail(f"local CLI did not create {path.name}")
        time.sleep(0.01)


def _wait_for_windows_child_exit(
    signals: Path, witness: str = "child-ready.json",
) -> None:
    import ctypes
    from ctypes import wintypes
    pid = json.loads((signals / witness).read_text("utf-8"))["pid"]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE, no mutation.
    if handle:
        try:
            assert kernel.WaitForSingleObject(handle, 5000) == 0
        finally:
            kernel.CloseHandle(handle)
    else:
        assert ctypes.get_last_error() == 87  # Already gone, not access denied.


@pytest.fixture
def local_cli(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    script = tmp_path / "local_cli.py"
    script.write_text(_LOCAL_CLI, encoding="utf-8")
    signals = tmp_path / "signals"
    signals.mkdir()
    try:
        yield script, signals
    finally:
        (signals / "release-child").touch()
        if (signals / "child-ready.json").exists():
            if os.name == "nt":
                _wait_for_windows_child_exit(signals)
            else:
                _wait_for(signals / "child-finished")


def _local_provider(
    monkeypatch: pytest.MonkeyPatch,
    local_cli: tuple[Path, Path],
    *,
    mode: str = "success",
) -> HostStructuredCliProvider:
    script, signals = local_cli
    monkeypatch.setenv("CODEX_HOME", str(signals.parent / "fictional-codex-home"))
    build_invocation = host_structured_cli._build_host_invocation

    def build_local_invocation(**kwargs):
        invocation = build_invocation(**kwargs)
        return replace(
            invocation,
            command=[
                sys.executable, "-I", "-u", str(script), mode, str(signals),
                *invocation.command[1:],
            ],
        )

    monkeypatch.setattr(
        host_structured_cli, "_build_host_invocation", build_local_invocation,
    )
    provider = HostStructuredCliProvider(
        host_client="codex", executable=sys.executable, poll_seconds=0.2,
    )
    # Shorten only the test's deadline; the real communicate/kill logic remains.
    provider.timeout_seconds = 10
    return provider


@contextmanager
def _held_child_invocation(
    provider: HostStructuredCliProvider, signals: Path, runtime_dir: Path,
) -> Iterator[Future[ProviderResult]]:
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            provider.assimilate, {"verified_candidates": []},
            runtime_dir=runtime_dir,
        )
        try:
            _wait_for(signals / "child-ready.json")
            _wait_for(signals / "parent-exiting")
            yield future
        finally:
            # Release even on a regression; never leave readers/children hanging.
            (signals / "release-child").touch()


def test_minimal_reproduction_parent_exits_before_inherited_pipes_reach_eof(
    local_cli: tuple[Path, Path], tmp_path: Path,
) -> None:
    script, signals = local_cli
    process = subprocess.Popen(
        [
            sys.executable, "-I", "-u", str(script), "success", str(signals),
            "--output-last-message", str(tmp_path / "decision.json"),
        ],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        assert process.stdin is not None
        process.stdin.close()
        process.stdin = None
        assert process.wait(timeout=5) == 0
        inherited = json.loads((signals / "child-ready.json").read_text("utf-8"))
        assert inherited["stdout_pipe"] is True
        assert inherited["stderr_pipe"] is True
        assert not (signals / "child-finished").exists()
        with pytest.raises(subprocess.TimeoutExpired):
            process.communicate(timeout=0.2)
        assert process.returncode == 0
    finally:
        (signals / "release-child").touch()
        if process.poll() is None:
            process.kill()
        stdout, stderr = process.communicate(timeout=5)
    assert '"total_tokens": 125' in stdout
    assert "local CLI diagnostic" in stderr


@pytest.mark.parametrize("mode", ["success", "startup"])
def test_provider_completes_and_removes_child_held_invocation_directory(
    local_cli: tuple[Path, Path], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    _, signals = local_cli
    provider = _local_provider(monkeypatch, local_cli, mode=mode)
    with _held_child_invocation(provider, signals, tmp_path / "runtime") as future:
        result = future.result(timeout=3)
        assert not (signals / "child-finished").exists()
        assert isinstance(result.decision, AssimilationDecision)
        assert result.decision.points == []
        assert result.provider == "codex_cli"
        raw = (signals / "decision.json").read_text("utf-8")
        assert result.response_sha256 == hashlib.sha256(raw.encode()).hexdigest()
        assert (signals / "stdin.txt").read_text("utf-8")
        assert result.total_tokens == 125
        if os.name == "nt":
            _wait_for_windows_child_exit(signals)
        assert not list((tmp_path / "runtime").glob("assimilation-*"))
        witness = json.loads((signals / "child-ready.json").read_text("utf-8"))
        assert not Path(witness["cwd"]).exists()


def test_nonzero_exit_with_valid_decision_file_is_not_success(
    local_cli: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, signals = local_cli
    provider = _local_provider(monkeypatch, local_cli, mode="nonzero")
    with _held_child_invocation(provider, signals, tmp_path / "runtime") as future:
        with pytest.raises(ProviderError, match="authentication denied") as raised:
            future.result(timeout=3)
        assert raised.value.exit_code == 7
        assert raised.value.kind == "auth_invalid"
        assert json.loads((signals / "decision.json").read_text("utf-8")) == {
            "points": [],
        }
        assert not (signals / "child-finished").exists()


def test_zero_exit_still_requires_valid_decision_schema(
    local_cli: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, signals = local_cli
    provider = _local_provider(monkeypatch, local_cli, mode="invalid")
    with _held_child_invocation(provider, signals, tmp_path / "runtime") as future:
        with pytest.raises(ProviderError, match="invalid assimilation JSON") as raised:
            future.result(timeout=3)
        assert raised.value.kind == "unrecoverable"
        assert raised.value.exit_code == 0
        assert not (signals / "child-finished").exists()


def test_running_parent_with_valid_decision_file_really_times_out(
    local_cli: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, signals = local_cli
    provider = _local_provider(monkeypatch, local_cli, mode="timeout")
    provider.timeout_seconds = 2
    heartbeats: list[float] = []
    with pytest.raises(ProviderError, match="provider exceeded 2s") as raised:
        provider.assimilate(
            {"verified_candidates": []}, runtime_dir=tmp_path / "runtime",
            heartbeat=lambda: heartbeats.append(time.monotonic()),
        )
    assert raised.value.kind == "transient"
    assert heartbeats
    assert (signals / "parent-running").exists()
    assert not (signals / "parent-exiting").exists()
    assert json.loads((signals / "decision.json").read_text("utf-8")) == {
        "points": [],
    }


@pytest.mark.skipif(os.name != "nt", reason="Windows process containment")
@pytest.mark.parametrize("failure", ["create", "limits", "assign", "resume", "terminate"])
def test_process_scope_failure_is_not_reported_as_success(
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    import ctypes
    events: list[str] = []
    kernel = SimpleNamespace(
        CreateJobObjectW=lambda *_args: 0 if failure == "create" else 11,
        AssignProcessToJobObject=lambda *_args: failure != "assign",
        SetInformationJobObject=lambda *_args: failure != "limits",
        NtResumeProcess=lambda *_args: -1 if failure == "resume" else 0,
        TerminateJobObject=lambda *_args: failure != "terminate",
        CloseHandle=lambda *_args: events.append("closed") or True,
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel)
    monkeypatch.setattr(
        host_structured_cli, "_terminate_process_tree",
        lambda _process: events.append("stopped") or ("", ""),
    )
    with pytest.raises(ProviderError):
        with host_structured_cli._invocation_process_scope(
            SimpleNamespace(_handle=22), enabled=True,
        ):
            events.append("body")
    assert events == {
        "create": ["stopped"],
        "limits": ["stopped", "closed"],
        "assign": ["stopped", "closed"],
        "resume": ["closed"],
        "terminate": ["body", "closed"],
    }[failure]


@pytest.mark.skipif(os.name != "nt", reason="Windows process containment")
def test_worker_crash_closes_job_and_stops_cli_and_early_child(
    local_cli: tuple[Path, Path], tmp_path: Path,
) -> None:
    script, signals = local_cli
    worker = tmp_path / "worker.py"
    worker.write_text('''
from dataclasses import replace
import os
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from harness_mem.autonomous.executors import host_structured_cli as cli
script, signals, runtime = sys.argv[2:]
os.environ["CODEX_HOME"] = str(Path(runtime) / "fictional-codex-home")
build = cli._build_host_invocation
def local(**kwargs):
    invocation = build(**kwargs)
    return replace(invocation, command=[sys.executable, "-I", "-u", script,
        "startup-timeout", signals, *invocation.command[1:]])
cli._build_host_invocation = local
provider = cli.HostStructuredCliProvider(host_client="codex", executable=sys.executable,
    poll_seconds=0.2)
def crash():
    if (Path(signals) / "parent-running").is_file():
        os._exit(17)  # No finally blocks; Windows must close the non-inherited Job.
provider.assimilate({}, runtime_dir=Path(runtime), heartbeat=crash)
''', encoding="utf-8")
    process = subprocess.Popen([
        sys.executable, "-I", str(worker), str(Path(__file__).resolve().parents[2]),
        str(script), str(signals), str(tmp_path / "runtime"),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        _, stderr = process.communicate(timeout=10)
        assert process.returncode == 17, stderr.decode("utf-8", errors="replace")
        _wait_for_windows_child_exit(signals, "parent-ready.json")
        _wait_for_windows_child_exit(signals)
        assert not (signals / "child-finished").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
