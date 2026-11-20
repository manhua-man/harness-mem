"""Isolated task-budget checks. The transport double never starts a host."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from harness_mem.autonomous.executors.host_structured_cli import HostStructuredCliProvider
from harness_mem.autonomous.executors.task_budget import (
    NativeDispatchRequest,
    NativeDispatchResult,
    TaskBudgetBinding,
    TaskBudgetRefusal,
    dispatch_with_task_budget,
    fake_input_capability,
    fake_output_limit_surface,
    host_input_capability,
    host_output_limit_surface,
    read_task_budget_receipt,
    task_budget_coverage,
    task_budget_receipt_path,
)
from harness_mem.commands.config_cmds import cmd_config_list, cmd_config_set
from harness_mem.config.errors import ConfigValidationError
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.config.writer import set_value


class Clock:
    def __init__(self, now: float = 50.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeNative:
    """Records dispatch requests. It has no subprocess and no host executable."""

    def __init__(self, results: list[object]) -> None:
        self.results = list(results)
        self.requests: list[NativeDispatchRequest] = []

    def __call__(self, request: NativeDispatchRequest) -> object:
        self.requests.append(request)
        outcome = self.results.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _redirect_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)


def _budget_config(**overrides: object) -> MergedConfig:
    values: dict[str, object] = {
        "task_model_budget_max_calls": 3,
        "task_model_budget_max_seconds": 100,
        "task_model_budget_max_input_tokens": 1000,
        "task_model_budget_max_output_tokens": 400,
        "task_model_budget_host_max_output_tokens": 50,
    }
    values.update(overrides)
    return MergedConfig(**values)  # type: ignore[arg-type]


def _binding(
    tmp_path: Path,
    config: MergedConfig,
    *,
    task_scope: str = "task-stable",
    host_client: str = "fake-host",
) -> TaskBudgetBinding:
    return TaskBudgetBinding(
        task_scope=task_scope,
        host_client=host_client,
        data_dir=tmp_path / "data",
        config=config,
    )


def _exact(
    *,
    status: str = "completed",
    input_tokens: int = 10,
    output_tokens: int = 4,
    duration_seconds: float = 2.0,
) -> NativeDispatchResult:
    return NativeDispatchResult(
        status=status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_seconds=duration_seconds,
        usage_exact=True,
    )


def _dispatch(
    binding: TaskBudgetBinding,
    transport: FakeNative,
    *,
    phase: str = "source",
    slice_id: str = "slice-1",
    runtime_dir: str | None = "runtime-a",
    timeout_seconds: int = 30,
    retry_of: str | None = None,
    clock: Clock | None = None,
    input_bound_tokens: int | None = 40,
    enforced_by_adapter: bool = False,
):
    capability = None
    if input_bound_tokens is not None:
        capability = fake_input_capability(
            binding.host_client,
            input_bound_tokens,
            enforced_by_adapter=enforced_by_adapter,
        )
    return dispatch_with_task_budget(
        binding,
        transport=transport,
        timeout_seconds=timeout_seconds,
        phase=phase,  # type: ignore[arg-type]
        slice_id=slice_id,
        clock=clock or Clock(),
        runtime_dir=runtime_dir,
        output_limit_surface=fake_output_limit_surface(binding.host_client),
        input_capability=capability,
        retry_of=retry_of,
    )


def test_dispatch_denial_happens_before_the_transport(tmp_path: Path) -> None:
    transport = FakeNative([_exact()])
    with pytest.raises(TaskBudgetRefusal) as missing:
        dispatch_with_task_budget(
            None,
            transport=transport,
            timeout_seconds=30,
            phase="source",
            slice_id="slice-1",
            output_limit_surface=fake_output_limit_surface(),
        )
    assert missing.value.code == "task_binding_missing"

    partial = _budget_config(task_model_budget_max_calls=None)
    with pytest.raises(TaskBudgetRefusal) as unset:
        _dispatch(_binding(tmp_path, partial), transport)
    assert unset.value.code == "bounds_not_configured"
    assert "max_calls" in str(unset.value)
    assert "not unlimited" in str(unset.value)

    exhausted = _budget_config(task_model_budget_max_calls=1)
    binding = _binding(tmp_path, exhausted)
    _dispatch(binding, FakeNative([_exact()]), slice_id="slice-1")
    blocked = FakeNative([_exact()])
    with pytest.raises(TaskBudgetRefusal) as denied:
        _dispatch(binding, blocked, slice_id="slice-2")
    assert denied.value.code == "call_budget_exhausted"
    assert blocked.requests == []
    assert transport.requests == []
    assert not task_budget_receipt_path(tmp_path / "data", "unused").exists()


@pytest.mark.parametrize(
    "host_client",
    ["codex", "claude-code", "hermes", "opencode", "antigravity"],
)
def test_production_hosts_refuse_unproven_output_caps(
    tmp_path: Path, host_client: str
) -> None:
    surface = host_output_limit_surface(host_client)
    assert surface.enforced is False
    assert surface.provenance == "local_cli_inspection"
    transport = FakeNative([_exact()])
    binding = _binding(tmp_path, _budget_config(), host_client=host_client)
    with pytest.raises(TaskBudgetRefusal) as refused:
        dispatch_with_task_budget(
            binding,
            transport=transport,
            timeout_seconds=30,
            phase="source",
            slice_id="slice-1",
            clock=Clock(),
        )
    assert refused.value.code == "host_output_limit_unsupported"
    assert transport.requests == []
    assert read_task_budget_receipt(binding.data_dir, binding.task_scope) is None
    with pytest.raises(TaskBudgetRefusal):
        fake_output_limit_surface(host_client)
    catalog = host_input_capability(host_client)
    assert catalog.max_complete_input_tokens is None
    assert catalog.provenance == "unproven"
    assert catalog.enforced_by_adapter is False
    with pytest.raises(TaskBudgetRefusal) as input_bound:
        fake_input_capability(host_client, 10)
    assert input_bound.value.code == "complete_input_bound_unknown"


def test_retries_malformed_results_and_reported_zero(tmp_path: Path) -> None:
    binding = _binding(tmp_path, _budget_config(task_model_budget_max_calls=3))
    malformed = FakeNative([{"not": "a result"}])
    with pytest.raises(TaskBudgetRefusal) as bad:
        _dispatch(binding, malformed, slice_id="slice-1")
    assert bad.value.code == "malformed_native_result"
    held = read_task_budget_receipt(binding.data_dir, binding.task_scope)
    assert held is not None
    assert held["calls"][0]["status"] == "malformed"
    assert held["calls"][0]["usage_exact"] is False
    assert held["calls"][0]["model_completion"] is False
    retry = FakeNative([_exact()])
    with pytest.raises(TaskBudgetRefusal) as blocked:
        _dispatch(binding, retry, slice_id="slice-1", retry_of=held["calls"][0]["call_id"])
    assert blocked.value.code == "remaining_not_demonstrable"
    assert retry.requests == []

    other = _binding(tmp_path, _budget_config(), task_scope="task-retry")
    first = FakeNative([_exact(status="failed", input_tokens=3, output_tokens=1)])
    failed = _dispatch(other, first, slice_id="slice-1")
    assert failed.receipt["calls"][0]["status"] == "failed"
    assert failed.receipt["calls"][0]["model_completion"] is False
    second = FakeNative([_exact(input_tokens=4, output_tokens=2)])
    retried = _dispatch(
        other,
        second,
        slice_id="slice-1",
        retry_of=failed.call_id,
    )
    assert retried.request.output_limit_argv == ("--max-output-tokens", "50")
    assert [row["status"] for row in retried.receipt["calls"]] == ["failed", "completed"]
    assert retried.receipt["calls"][1]["retry_of"] == failed.call_id
    zeros = _binding(tmp_path, _budget_config(), task_scope="task-zero")
    reported = _dispatch(
        zeros,
        FakeNative([_exact(input_tokens=0, output_tokens=0, duration_seconds=1)]),
    )
    assert reported.receipt["calls"][0]["usage"] == {
        "duration_seconds": 1.0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    missing = NativeDispatchResult(status="failed", usage_exact=True)
    denied = FakeNative([missing])
    fresh = _binding(tmp_path, _budget_config(), task_scope="task-missing-usage")
    _dispatch(fresh, denied)
    assert denied.requests
    follow = FakeNative([_exact()])
    with pytest.raises(TaskBudgetRefusal) as unknown:
        _dispatch(fresh, follow, slice_id="slice-2")
    assert unknown.value.code == "remaining_not_demonstrable"
    assert follow.requests == []


def test_unknown_usage_and_cancellation_keep_the_reservation(tmp_path: Path) -> None:
    binding = _binding(tmp_path, _budget_config())
    crashing = FakeNative([RuntimeError("native failed before usage")])
    with pytest.raises(RuntimeError, match="native failed before usage"):
        _dispatch(binding, crashing)
    receipt = read_task_budget_receipt(binding.data_dir, binding.task_scope)
    assert receipt is not None
    assert receipt["calls"][0]["status"] == "unknown"
    assert receipt["calls"][0]["usage"]["input_tokens"] is None
    assert receipt["calls"][0]["reserved"]["input_tokens"] == 40
    assert receipt["calls"][0]["input_bound"]["adapter_enforces_bound"] is False
    assert receipt["cancellation_is_model_completion"] is False
    follow = FakeNative([_exact()])
    with pytest.raises(TaskBudgetRefusal) as blocked:
        _dispatch(binding, follow, slice_id="slice-2")
    assert blocked.value.code == "remaining_not_demonstrable"
    assert follow.requests == []

    cancelled_task = _binding(tmp_path, _budget_config(), task_scope="task-cancel")
    cancelled = _dispatch(
        cancelled_task,
        FakeNative([NativeDispatchResult(status="cancelled", usage_exact=False)]),
    )
    assert cancelled.receipt["calls"][0]["model_completion"] is False
    assert cancelled.receipt["calls"][0]["usage_exact"] is False
    with pytest.raises(TaskBudgetRefusal):
        _dispatch(cancelled_task, FakeNative([_exact()]), slice_id="slice-2")


def test_continuation_reopens_one_ledger_across_runtime_directories(tmp_path: Path) -> None:
    config = _budget_config()
    first_binding = _binding(tmp_path, config)
    clock = Clock(50.0)
    first = _dispatch(
        first_binding,
        FakeNative([_exact(input_tokens=11, output_tokens=6, duration_seconds=3)]),
        slice_id="slice-1",
        runtime_dir="runtime-a",
        clock=clock,
    )
    reopened = _binding(tmp_path, config)
    second = _dispatch(
        reopened,
        FakeNative([_exact(input_tokens=7, output_tokens=5, duration_seconds=4)]),
        slice_id="slice-2",
        runtime_dir="runtime-b",
        clock=clock,
    )
    assert first.call_id != second.call_id
    assert second.receipt["task_scope"] == "task-stable"
    assert [row["runtime_dir"] for row in second.receipt["calls"]] == [
        "runtime-a",
        "runtime-b",
    ]
    assert second.receipt["calls"][0]["reserved_at"] == 50.0
    stored = read_task_budget_receipt(reopened.data_dir, reopened.task_scope)
    assert stored is not None
    assert len(stored["calls"]) == 2
    receipts = list((tmp_path / "data" / "autonomous" / "receipts" / "task-model-budget").glob("*.json"))
    assert len(receipts) == 1


def test_source_and_dream_share_one_task_budget(tmp_path: Path) -> None:
    binding = _binding(tmp_path, _budget_config(task_model_budget_max_output_tokens=80))
    source = _dispatch(
        binding,
        FakeNative([_exact(input_tokens=20, output_tokens=50, duration_seconds=5)]),
        phase="source",
        slice_id="source-slice",
        runtime_dir="provider-runtime",
    )
    dream = _dispatch(
        binding,
        FakeNative([_exact(input_tokens=8, output_tokens=9, duration_seconds=2)]),
        phase="dream",
        slice_id="dream-slice",
        runtime_dir="another-provider-runtime",
    )
    assert source.receipt["phase_handoff_resets_budget"] is False
    assert dream.request.output_limit_tokens == 30
    assert dream.request.output_limit_argv == ("--max-output-tokens", "30")
    assert [row["phase"] for row in dream.receipt["calls"]] == ["source", "dream"]
    assert dream.receipt["calls"][1]["usage"]["output_tokens"] == 9

    other = _binding(
        tmp_path,
        _budget_config(task_model_budget_max_calls=1),
        task_scope="other-task",
    )
    _dispatch(other, FakeNative([_exact()]), runtime_dir="provider-runtime")
    with pytest.raises(TaskBudgetRefusal) as exhausted:
        _dispatch(other, FakeNative([_exact()]), slice_id="slice-2", runtime_dir="provider-runtime")
    assert exhausted.value.code == "call_budget_exhausted"
    fresh = _binding(tmp_path, _budget_config(), task_scope="fresh-task")
    opened = _dispatch(fresh, FakeNative([_exact()]), runtime_dir="provider-runtime")
    assert opened.receipt["calls"][0]["usage"]["input_tokens"] == 10


def test_completed_usage_replaces_the_conservative_reservation(tmp_path: Path) -> None:
    binding = _binding(tmp_path, _budget_config())
    done = _dispatch(
        binding,
        FakeNative([_exact(input_tokens=12, output_tokens=7, duration_seconds=2.2)]),
        input_bound_tokens=100,
    )
    call = done.receipt["calls"][0]
    assert call["reserved"]["input_tokens"] == 100
    assert call["reserved"]["output_tokens"] == 50
    assert call["usage"] == {
        "duration_seconds": 2.2,
        "input_tokens": 12,
        "output_tokens": 7,
    }
    assert call["usage_exact"] is True
    assert call["model_completion"] is True
    # 901 fits the reconciled remainder (988). It would not fit if the
    # unused part of the 100-token hold were still consumed (remainder 900).
    nxt = _dispatch(
        binding,
        FakeNative([_exact(input_tokens=1, output_tokens=1, duration_seconds=1)]),
        slice_id="slice-2",
        input_bound_tokens=901,
    )
    assert nxt.request.output_limit_tokens == 50
    assert nxt.request.input_bound_tokens == 901
    assert nxt.receipt["calls"][1]["reserved"]["input_tokens"] == 901

    over = _binding(tmp_path, _budget_config(), task_scope="task-over")
    exceeded = _dispatch(
        over,
        FakeNative([_exact(output_tokens=51, input_tokens=1, duration_seconds=1)]),
    )
    assert exceeded.receipt["calls"][0]["bound_exceeded"] is True
    assert exceeded.receipt["calls"][0]["model_completion"] is False
    with pytest.raises(TaskBudgetRefusal) as stopped:
        _dispatch(over, FakeNative([_exact()]), slice_id="slice-2")
    assert stopped.value.code == "remaining_not_demonstrable"


def test_time_budget_and_corrupt_or_changed_ledger_fail_closed(tmp_path: Path) -> None:
    short = _binding(tmp_path, _budget_config(task_model_budget_max_seconds=20))
    transport = FakeNative([_exact()])
    with pytest.raises(TaskBudgetRefusal) as timed:
        _dispatch(short, transport, timeout_seconds=30)
    assert timed.value.code == "time_budget_exhausted"
    assert transport.requests == []

    binding = _binding(tmp_path, _budget_config(), task_scope="task-corrupt")
    path = task_budget_receipt_path(binding.data_dir, binding.task_scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")
    corrupt_transport = FakeNative([_exact()])
    with pytest.raises(TaskBudgetRefusal) as corrupt:
        _dispatch(binding, corrupt_transport)
    assert corrupt.value.code == "receipt_unreadable"
    assert corrupt_transport.requests == []
    assert path.read_text(encoding="utf-8") == "{"

    original = _budget_config(task_model_budget_max_calls=2)
    stable = _binding(tmp_path, original, task_scope="task-frozen")
    _dispatch(stable, FakeNative([_exact()]))
    changed = _binding(
        tmp_path,
        _budget_config(task_model_budget_max_calls=9),
        task_scope="task-frozen",
    )
    changed_transport = FakeNative([_exact()])
    with pytest.raises(TaskBudgetRefusal) as frozen:
        _dispatch(changed, changed_transport, slice_id="slice-2")
    assert frozen.value.code == "task_bounds_changed"
    assert changed_transport.requests == []
    stored = read_task_budget_receipt(stable.data_dir, stable.task_scope)
    assert stored is not None
    assert stored["bounds"]["max_calls"] == 2

    switched = _binding(
        tmp_path,
        original,
        task_scope="task-frozen",
        host_client="other-fake",
    )
    with pytest.raises(TaskBudgetRefusal) as host:
        _dispatch(switched, FakeNative([_exact()]), slice_id="slice-3")
    assert host.value.code == "task_host_changed"


def test_returned_context_defaults_and_project_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _redirect_home(monkeypatch, home)
    untouched = tmp_path / "empty-project"
    untouched.mkdir()
    defaults = load_merged_config(untouched)
    assert defaults.task_model_budget_max_calls == 64
    assert defaults.cost_budget_wake_tokens == 2000
    assert defaults.cost_budget_search_tokens == 1200
    assert defaults.cost_budget_file_context_tokens == 900
    assert defaults.cost_budget_dream_tokens == 2000
    assert defaults.cost_budget_distill_tokens == 3000
    assert task_budget_coverage(defaults)["missing_bounds"] == []
    runtime = defaults.to_runtime_config()
    assert runtime["task_model_budget"] == {
        "max_calls": 64,
        "max_seconds": 3600,
        "max_input_tokens": 2_000_000,
        "max_output_tokens": 128_000,
        "host_max_output_tokens": None,
    }
    assert json.loads(json.dumps(runtime))["task_model_budget"]["max_seconds"] == 3600
    assert runtime["cost_budget"]["wake_tokens"] == 2000
    assert cmd_config_list(str(untouched), detail="runtime") == 0
    listed = capsys.readouterr().out
    public_view, runtime_view = listed.split("runtime tuning (read-only):", 1)
    assert "task_model_budget." in public_view
    assert "task_model_budget.max_calls = 64  (default)" in public_view
    assert "task_model_budget.max_seconds = 3600  (default)" in public_view
    assert "task_model_budget.max_input_tokens = 2000000  (default)" in public_view
    assert "cost_budget.wake_tokens = 2000  (default)" in runtime_view
    user = home / ".harness-mem" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        "\n".join(
            [
                "[cost_budget]",
                "wake_tokens = 1500",
                "[task_model_budget]",
                "max_calls = 2",
                "max_seconds = 10",
                "max_input_tokens = 10",
                "max_output_tokens = 10",
                "host_max_output_tokens = 4",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (project / ".harness-mem.toml").write_text(
        "[task_model_budget]\nmax_calls = 5\n",
        encoding="utf-8",
    )

    config = load_merged_config(project)
    assert config.cost_budget_wake_tokens == 1500
    assert config.cost_budget_search_tokens == 1200
    assert config.cost_budget_file_context_tokens == 900
    assert config.cost_budget_dream_tokens == 2000
    assert config.cost_budget_distill_tokens == 3000
    assert config.task_model_budget_max_calls == 5
    assert config.task_model_budget_max_seconds == 10
    assert config.task_model_budget_host_max_output_tokens == 4
    coverage = task_budget_coverage(config)
    assert coverage["returned_context_budgets"]["not_task_model_consumption"] is True
    assert coverage["returned_context_budgets"]["cost_budget.wake_tokens"] == 1500
    assert coverage["task_bounds"]["max_calls"]["covers"] == "whole_task"
    assert coverage["task_bounds"]["host_max_output_tokens"]["covers"] == "one_native_request"
    assert coverage["background_authorization_required"] is False
    assert coverage["usage_from_text_length"] is False
    assert coverage["cross_host_equivalence"] is False
    assert coverage["task_bounds"]["max_seconds"]["covers"] == (
        "whole_task_cumulative_native_request_time"
    )
    assert coverage["task_bounds"]["max_seconds"]["includes_lifecycle_wall_wait"] is False
    assert "wall_duration_seconds" in coverage["max_seconds_means"]
    assert "not a hard native cap" in coverage["complete_native_input_bound_means"]

    invalid = tmp_path / "invalid-project"
    invalid.mkdir()
    (invalid / ".harness-mem.toml").write_text(
        "[task_model_budget]\nmax_calls = 0\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError):
        load_merged_config(invalid)

    assert cmd_config_set(
        "task_model_budget.max_calls", "4", "project", str(project)
    ) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert cmd_config_list(str(project)) == 0
    assert "task_model_budget.max_calls" in capsys.readouterr().out

    written = set_value(
        scope="project",
        project_root=project,
        key_path="capture.enabled",
        value="false",
    )
    text = written.read_text(encoding="utf-8")
    assert "enabled = false" in text
    reloaded = load_merged_config(project)
    assert reloaded.capture_enabled is False
    assert reloaded.task_model_budget_max_calls == 4
    assert reloaded.task_model_budget_max_seconds == 10
    assert reloaded.cost_budget_wake_tokens == 1500
    assert reloaded.cost_budget_search_tokens == 1200


def test_budget_gate_ignores_background_authorization_and_real_executables(
    tmp_path: Path,
) -> None:
    config = _budget_config()
    assert config.distill_autonomous_enabled is False
    binding = _binding(tmp_path, config)
    transport = FakeNative([_exact(input_tokens=2, output_tokens=2, duration_seconds=1)])
    provider = HostStructuredCliProvider(
        host_client="fake-host",
        executable="not-a-real-host-binary",
    )
    completed = provider.dispatch_with_task_budget(
        binding,
        transport=transport,
        timeout_seconds=30,
        phase="source",
        slice_id="slice-1",
        clock=Clock(),
        output_limit_surface=fake_output_limit_surface("fake-host"),
        input_capability=fake_input_capability("fake-host", 40),
    )
    assert completed.receipt["background_authorization_required"] is False
    assert transport.requests[0].output_limit_argv == ("--max-output-tokens", "50")
    assert transport.requests[0].input_bound_tokens == 40
    assert transport.requests[0].input_bound_enforced_by_adapter is False
    assert transport.requests[0].host_client == "fake-host"
    mismatch = FakeNative([_exact()])
    with pytest.raises(TaskBudgetRefusal) as refused:
        provider.dispatch_with_task_budget(
            _binding(tmp_path, config, host_client="other-fake"),
            transport=mismatch,
            timeout_seconds=30,
            phase="source",
            slice_id="slice-9",
            output_limit_surface=fake_output_limit_surface("other-fake"),
        )
    assert refused.value.code == "host_binding_missing"
    assert mismatch.requests == []

    hermes = HostStructuredCliProvider(host_client="hermes", executable="hermes-not-launched")
    hermes_transport = FakeNative([_exact()])
    with pytest.raises(TaskBudgetRefusal) as unsupported:
        hermes.dispatch_with_task_budget(
            _binding(tmp_path, config, host_client="hermes", task_scope="hermes-task"),
            transport=hermes_transport,
            timeout_seconds=30,
            phase="dream",
            slice_id="dream-1",
            clock=Clock(),
        )
    assert unsupported.value.code == "host_output_limit_unsupported"
    assert hermes_transport.requests == []


def test_exact_cancellation_consumes_usage_without_counting_completion(
    tmp_path: Path,
) -> None:
    binding = _binding(tmp_path, _budget_config())
    cancelled = _dispatch(
        binding,
        FakeNative([
            _exact(status="cancelled", input_tokens=15, output_tokens=6, duration_seconds=4)
        ]),
    )
    assert cancelled.receipt["calls"][0]["usage_exact"] is True
    assert cancelled.receipt["calls"][0]["model_completion"] is False
    assert cancelled.receipt["cancellation_is_model_completion"] is False
    nxt = _dispatch(
        binding,
        FakeNative([_exact(input_tokens=1, output_tokens=1, duration_seconds=1)]),
        phase="dream",
        slice_id="after-cancel",
    )
    assert nxt.receipt["calls"][1]["reserved"]["input_tokens"] == 40
    assert nxt.request.input_bound_tokens == 40


def test_complete_native_input_bound_gates_before_transport(tmp_path: Path) -> None:
    unknown_transport = FakeNative([_exact(input_tokens=1001)])
    unknown_binding = _binding(tmp_path, _budget_config(), task_scope="input-unknown")
    catalog = host_input_capability("fake-host")
    assert catalog.max_complete_input_tokens is None
    assert catalog.provenance == "unproven"
    assert catalog.enforced_by_adapter is False
    with pytest.raises(TaskBudgetRefusal) as unknown:
        dispatch_with_task_budget(
            unknown_binding,
            transport=unknown_transport,
            timeout_seconds=30,
            phase="source",
            slice_id="slice-1",
            clock=Clock(),
            output_limit_surface=fake_output_limit_surface("fake-host"),
        )
    assert unknown.value.code == "complete_input_bound_unknown"
    assert unknown_transport.requests == []
    assert read_task_budget_receipt(
        unknown_binding.data_dir, unknown_binding.task_scope
    ) is None

    oversized_transport = FakeNative([_exact(input_tokens=1)])
    oversized = _binding(tmp_path, _budget_config(), task_scope="input-oversized")
    with pytest.raises(TaskBudgetRefusal) as too_big:
        _dispatch(oversized, oversized_transport, input_bound_tokens=1001)
    assert too_big.value.code == "input_budget_exhausted"
    assert oversized_transport.requests == []
    assert read_task_budget_receipt(oversized.data_dir, oversized.task_scope) is None

    valid_transport = FakeNative([
        _exact(input_tokens=12, output_tokens=4, duration_seconds=2)
    ])
    valid = _binding(tmp_path, _budget_config(), task_scope="input-valid")
    done = _dispatch(valid, valid_transport, input_bound_tokens=30)
    assert len(valid_transport.requests) == 1
    assert valid_transport.requests[0].host_client == "fake-host"
    assert valid_transport.requests[0].input_bound_tokens == 30
    assert valid_transport.requests[0].input_bound_enforced_by_adapter is False
    call = done.receipt["calls"][0]
    assert call["reserved"]["input_tokens"] == 30
    assert call["usage"]["input_tokens"] == 12
    assert call["input_bound"]["adapter_enforces_bound"] is False
    assert call["input_bound"]["from_text_length"] is False
    assert call["input_bound"]["provenance"] == "test_double"
    assert call["model_completion"] is True
    follow_transport = FakeNative([_exact(input_tokens=1)])
    with pytest.raises(TaskBudgetRefusal) as follow:
        _dispatch(valid, follow_transport, slice_id="slice-2", input_bound_tokens=989)
    assert follow.value.code == "input_budget_exhausted"
    assert follow_transport.requests == []
    stored = read_task_budget_receipt(valid.data_dir, valid.task_scope)
    assert stored is not None
    assert len(stored["calls"]) == 1
    fitting = _dispatch(
        valid,
        FakeNative([_exact(input_tokens=4, output_tokens=1, duration_seconds=1)]),
        slice_id="slice-3",
        input_bound_tokens=988,
    )
    assert fitting.request.input_bound_tokens == 988
    assert fitting.receipt["calls"][1]["reserved"]["input_tokens"] == 988
    assert fitting.receipt["calls"][1]["usage"]["input_tokens"] == 4

    lied_transport = FakeNative([
        _exact(input_tokens=50, output_tokens=1, duration_seconds=1)
    ])
    lied = _binding(tmp_path, _budget_config(), task_scope="input-assumed")
    exceeded = _dispatch(lied, lied_transport, input_bound_tokens=20)
    assert lied_transport.requests
    assert exceeded.receipt["calls"][0]["bound_exceeded"] is True
    assert exceeded.receipt["calls"][0]["usage"]["input_tokens"] == 50
    assert exceeded.receipt["calls"][0]["input_bound"]["adapter_enforces_bound"] is False
    assert exceeded.receipt["calls"][0]["model_completion"] is False
    stopped = FakeNative([_exact()])
    with pytest.raises(TaskBudgetRefusal) as blocked:
        _dispatch(lied, stopped, slice_id="slice-2", input_bound_tokens=10)
    assert blocked.value.code == "remaining_not_demonstrable"
    assert stopped.requests == []


def test_concurrent_reopen_waits_for_exact_usage_before_next_reservation(tmp_path: Path) -> None:
    binding = _binding(
        tmp_path,
        _budget_config(task_model_budget_max_calls=2),
        task_scope="task-concurrent",
    )
    started = threading.Event()
    finish = threading.Event()

    class HeldNative(FakeNative):
        def __call__(self, request: NativeDispatchRequest) -> object:
            started.set()
            assert finish.wait(timeout=10)
            return super().__call__(request)

    reopened = _binding(
        tmp_path,
        _budget_config(task_model_budget_max_calls=2),
        task_scope="task-concurrent",
    )
    second = FakeNative([_exact()])
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(_dispatch, binding, HeldNative([_exact()]), slice_id="slice-a", input_bound_tokens=15)
        try:
            assert started.wait(timeout=5)
            with pytest.raises(TaskBudgetRefusal) as pending:
                _dispatch(reopened, second, slice_id="slice-b", input_bound_tokens=15)
            assert pending.value.code == "remaining_not_demonstrable"
            assert second.requests == []
        finally:
            finish.set()
        first.result(timeout=5)
    _dispatch(reopened, second, slice_id="slice-b", input_bound_tokens=15)
    receipt = read_task_budget_receipt(reopened.data_dir, reopened.task_scope)
    assert receipt is not None
    assert {row["slice_id"] for row in receipt["calls"]} == {"slice-a", "slice-b"}
    assert [row["reserved"]["input_tokens"] for row in receipt["calls"]] == [15, 15]
    blocked = FakeNative([_exact()])
    with pytest.raises(TaskBudgetRefusal) as denied:
        _dispatch(reopened, blocked, slice_id="slice-c", input_bound_tokens=15)
    assert denied.value.code == "call_budget_exhausted"
    assert blocked.requests == []


@pytest.mark.parametrize("key", ("max_calls", "max_seconds", "max_input_tokens", "max_output_tokens", "host_max_output_tokens"))
def test_public_budget_policy_roundtrip_and_invalid_write_preserves_file(tmp_path, monkeypatch, key):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    path = "task_model_budget." + key
    attribute = "task_model_budget_" + key
    set_value(scope="user", project_root=project, key_path=path, value="8")
    assert getattr(load_merged_config(project), attribute) == 8
    written = set_value(scope="project", project_root=project, key_path=path, value="4")
    assert getattr(load_merged_config(project), attribute) == 4
    previous = written.read_bytes()
    for invalid in ("0", "-1", "true", "3.5", "unlimited"):
        with pytest.raises(ConfigValidationError):
            set_value(scope="project", project_root=project, key_path=path, value=invalid)
        assert written.read_bytes() == previous
    assert getattr(load_merged_config(project), attribute) == 4
