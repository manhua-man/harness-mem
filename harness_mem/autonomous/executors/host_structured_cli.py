"""Structured host CLI invocations for authorized background agent mode."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable, Iterator, Mapping
from uuid import uuid4

from pydantic import ValidationError

from harness_mem.autonomous.models import (
    AgentExtractionDecision,
    AssimilationDecision,
    CandidateVerificationDecision,
)
from harness_mem.autonomous.provider import (
    ProviderError,
    ProviderResult,
    _build_assimilation_prompt,
    _build_prompt,
    _build_verification_prompt,
    _classify_failure,
    expand_agent_extraction_decision,
    _strict_output_schema,
    _usage_metrics,
)
from harness_mem.autonomous.hook_guard import (
    register_provider_process_lease,
    release_provider_process_lease,
)
from harness_mem.autonomous.executors.constants import host_cli_provider_name
from harness_mem.autonomous.executors.host_cli import _codex_background_overrides

_CODEX_MEMORY_INSTRUCTIONS = (
    "You are the harness-mem memory decision worker. Use only the supplied "
    "task and evidence. Do not call tools, inspect the host, or execute actions. "
    "Return only the requested JSON decision; the runtime verifies evidence "
    "and owns all memory writes."
)

_HOOK_GUARD_CHECKS: dict[str, tuple[str, ...]] = {
    "codex": (".codex", "hooks.json"),
    "claude-code": (".claude", "hooks"),
    "opencode": (".opencode", "plugins", "harness-mem.ts"),
    "antigravity": (".agents", "hooks.json"),
}


@dataclass(frozen=True)
class _CliInvocation:
    command: list[str]
    env: Mapping[str, str]
    output_path: Path | None
    output_from_stdout: bool = False
    stdin_text: str | None = None


@contextmanager
def _temporary_runtime_directory(*, prefix: str, parent: Path) -> Iterator[Path]:
    """Remove an invocation directory after short-lived Windows children exit."""

    path = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    try:
        yield path
    finally:
        _remove_runtime_directory(path)


def _remove_runtime_directory(path: Path) -> None:
    """Delete only the exact directory returned by this owner's mkdtemp."""
    for attempt in range(40):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.25)


def _assert_runtime_isolated(runtime_dir: Path, host_client: str) -> None:
    guard = _HOOK_GUARD_CHECKS.get(host_client)
    if guard is None:
        return
    target = runtime_dir.joinpath(*guard)
    if target.exists():
        raise ProviderError(
            f"autonomous provider cwd contains a {host_client} hook manifest",
            kind="setup_required",
        )


def _terminate_process_tree(process: subprocess.Popen[str]) -> tuple[str, str]:
    """Stop one timed-out CLI invocation without leaving Windows children alive."""

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    if process.poll() is None:
        process.kill()
    try:
        stdout, stderr = process.communicate(timeout=10)
        return stdout or "", stderr or ""
    except subprocess.TimeoutExpired:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return "", ""


@contextmanager
def _invocation_process_scope(
    process: subprocess.Popen[str], *, enabled: bool
) -> Iterator[None]:
    """Contain this Windows CLI's children, even after its parent has exited."""
    if not enabled or os.name != "nt":
        yield
        return
    # A named/global process scan could target an unrelated Codex session.
    # This anonymous Job Object contains only the process we just launched.
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", ctypes.c_ulonglong * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    native = ctypes.WinDLL("ntdll")
    native.NtResumeProcess.argtypes = [wintypes.HANDLE]
    native.NtResumeProcess.restype = wintypes.LONG
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        _terminate_process_tree(process)
        raise ProviderError("Cannot create CLI process scope", kind="setup_required")
    try:
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE.
        if not kernel.SetInformationJobObject(
            job, 9, ctypes.byref(limits), ctypes.sizeof(limits),
        ):
            _terminate_process_tree(process)
            raise ProviderError(
                "Cannot configure CLI process cleanup", kind="setup_required"
            )
        # Popen owns this Windows process handle until its object is released.
        if not kernel.AssignProcessToJobObject(job, int(getattr(process, "_handle"))):
            _terminate_process_tree(process)
            raise ProviderError(
                "Cannot contain CLI child processes", kind="setup_required"
            )
        try:
            # Popen closed the primary thread handle. Resume the suspended
            # process only after assignment, so startup children cannot escape.
            if native.NtResumeProcess(int(getattr(process, "_handle"))) < 0:
                raise ProviderError(
                    "Cannot start contained CLI process", kind="setup_required"
                )
            yield
        finally:
            if not kernel.TerminateJobObject(job, 1):
                raise ProviderError(
                    "Cannot stop CLI child processes", kind="transient"
                )
    finally:
        kernel.CloseHandle(job)


def _build_codex_like_command(
    *,
    executable: str,
    schema_path: Path,
    output_path: Path,
) -> _CliInvocation:
    command = [executable, "exec", "--ephemeral"]
    command.extend(
        [
            "--skip-git-repo-check",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "--json",
        ]
    )
    command.append("-")
    return _CliInvocation(command=command, env={}, output_path=output_path)


def _build_claude_code_command(
    *,
    executable: str,
    schema_path: Path,
) -> _CliInvocation:
    schema_json = schema_path.read_text(encoding="utf-8").strip()
    command = [
        executable,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        schema_json,
        "--dangerously-skip-permissions",
    ]
    command.append("-")
    return _CliInvocation(
        command=command,
        env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
        output_path=None,
        output_from_stdout=True,
    )


def _build_hermes_command(
    *,
    executable: str,
    prompt: str,
    usage_path: Path,
) -> _CliInvocation:
    # Hermes' one-shot mode is its native script surface: it keeps the user's
    # model, provider, credentials, rules, and memory while printing only the
    # final response. The prompt already contains the source excerpts needed for
    # this JSON-only decision, so unrelated tool schemas stay out of the request.
    command = [
        executable,
        "--toolsets",
        "context_engine",
        "--usage-file",
        str(usage_path),
        "-z",
        prompt,
    ]
    if os.name == "nt":
        # Hermes' -z entry takes its complete prompt in argv and has no
        # query-file support; Windows rejects long source packets before the
        # process starts. Enter the same installed CLI with its own Python,
        # restoring the original argv from UTF-8 stdin inside that process.
        # Keep -z (including its usage-file reporting), provider and model.
        python_executable = Path(executable).resolve().with_name("python.exe")
        if not python_executable.is_file():
            raise ProviderError(
                "Hermes background input on Windows requires python.exe "
                "beside the selected Hermes executable",
                kind="setup_required",
            )
        bootstrap = (
            "import sys; "
            "sys.argv = sys.argv[1:] + [sys.stdin.buffer.read().decode('utf-8')]; "
            "from hermes_cli.main import main; main()"
        )
        command = [str(python_executable), "-c", bootstrap, *command[:-1]]
    return _CliInvocation(
        command=command,
        env={},
        output_path=None,
        output_from_stdout=True,
    )


def _build_opencode_command(
    *,
    executable: str,
    schema_path: Path,
    output_path: Path,
) -> _CliInvocation:
    command = [
        executable,
        "run",
        "--format",
        "json",
        "--output-schema",
        str(schema_path),
        "--output",
        str(output_path),
    ]
    command.append("-")
    return _CliInvocation(command=command, env={}, output_path=output_path)


def _build_antigravity_command(
    *, executable: str, schema_path: Path, prompt: str,
) -> _CliInvocation:
    """Send one complete turn through agy's native stdin/schema protocol."""
    return _CliInvocation(
        command=[
            executable, "--input-format", "stream-json",
            "--output-format", "stream-json", "--json-schema", str(schema_path),
            "--agent", "harness-mem-worker", "--disable-slash-commands",
            "--mode", "plan",
        ],
        env={}, output_path=None, output_from_stdout=True,
        stdin_text=json.dumps(
            {"event": "user", "message": {"content": prompt}}, ensure_ascii=False,
        ) + "\n",
    )


def _write_antigravity_worker(execution_cwd: Path) -> None:
    agent = execution_cwd / ".agents" / "agents" / "harness-mem-worker.md"
    agent.parent.mkdir(parents=True, exist_ok=True)
    agent.write_text(
        "---\nname: harness-mem-worker\n"
        "description: Return a memory decision from supplied evidence only.\n"
        "mainAgent: true\nsubagent: false\nmodel: inherit\n"
        "tools: []\nmcpServers: []\nskills: []\nplugins: []\n"
        "commandExecutionPolicy: 'off'\n---\n" + _CODEX_MEMORY_INSTRUCTIONS + "\n",
        encoding="utf-8",
    )


def _build_host_invocation(
    *,
    host_client: str,
    executable: str,
    schema_path: Path,
    output_path: Path,
    prompt: str,
    usage_path: Path,
) -> _CliInvocation:
    if host_client == "codex":
        return _build_codex_like_command(
            executable=executable,
            schema_path=schema_path,
            output_path=output_path,
        )
    if host_client == "claude-code":
        return _build_claude_code_command(
            executable=executable,
            schema_path=schema_path,
        )
    if host_client == "hermes":
        return _build_hermes_command(
            executable=executable,
            prompt=prompt,
            usage_path=usage_path,
        )
    if host_client == "opencode":
        return _build_opencode_command(
            executable=executable,
            schema_path=schema_path,
            output_path=output_path,
        )
    if host_client == "antigravity":
        return _build_antigravity_command(
            executable=executable, schema_path=schema_path, prompt=prompt,
        )
    raise ProviderError(
        f"unsupported host client for structured CLI: {host_client}",
        kind="setup_required",
    )


def _normalize_cli_json_text(raw: str) -> str:
    payload = raw.strip()
    if payload.startswith("```"):
        lines = payload.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and lines[-1].strip() == "```":
            lines.pop()
        payload = "\n".join(lines).strip()
    return payload


def _coerce_json_text(raw: str) -> str:
    payload = _normalize_cli_json_text(raw)
    if not payload:
        raise ProviderError(
            "host CLI returned empty stdout",
            kind="unrecoverable",
        )
    try:
        json.loads(payload)
        return payload
    except json.JSONDecodeError:
        # Some host CLIs append a short status line or emit more than one
        # JSON envelope.  Recover the first complete object instead of taking
        # everything between the first and last brace (which makes otherwise
        # valid output fail when a trailing line contains another brace).
        decoder = json.JSONDecoder()
        for index, character in enumerate(payload):
            if character not in "[{":
                continue
            try:
                value, end = decoder.raw_decode(payload[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, (dict, list)):
                return payload[index : index + end]
        raise ProviderError(
            f"host CLI returned non-JSON output: {payload[:500]}",
            kind="unrecoverable",
        )


def _reported_cli_failure(raw: str) -> bool:
    """Recognize a CLI's plain-text transport failure despite exit code zero."""

    lowered = raw.strip().lower()
    return any(
        marker in lowered
        for marker in (
            "api call failed",
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "service temporarily unavailable",
            "connection refused",
            "connection reset",
            "timed out",
        )
    )


def _reject_codex_tool_activity(stdout: str) -> None:
    """Do not accept a JSON decision produced by an interactive tool workflow."""
    forbidden = {
        "command_execution", "mcp_tool_call", "file_change", "web_search",
        "collab_tool_call", "image_generation", "image_view", "dynamic_tool_call",
    }
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") in forbidden:
            raise ProviderError(
                "Codex memory decision attempted unexpected tool activity",
                kind="unrecoverable",
            )


def _extract_antigravity_result(stdout: str) -> tuple[str, str]:
    """Accept only one complete native stream; never mistake init for a decision."""
    initialized = False
    result: dict[str, Any] | None = None
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise ProviderError("Antigravity returned invalid NDJSON", kind="unrecoverable") from exc
        if not isinstance(event, dict) or result is not None:
            raise ProviderError("Antigravity returned an invalid event order", kind="unrecoverable")
        kind = event.get("event")
        if kind == "init" and not initialized:
            init = event.get("init")
            if not isinstance(init, dict) or init.get("tools") != []:
                raise ProviderError("Antigravity worker tools are not disabled", kind="setup_required")
            if init.get("agent") != "harness-mem-worker":
                raise ProviderError("Antigravity did not select the memory worker", kind="setup_required")
            initialized = True
        elif kind == "step_update" and initialized:
            step = event.get("step_update")
            if (
                not isinstance(step, dict)
                or step.get("step_type") not in {"user_input", "agent_response", "checkpoint"}
                or any(step.get(key) for key in ("tool_name", "tool_info", "subagent_info"))
            ):
                raise ProviderError("Antigravity memory worker attempted tool activity", kind="unrecoverable")
        elif kind == "result" and initialized and isinstance(event.get("result"), dict):
            result = event["result"]
        else:
            raise ProviderError("Antigravity returned an unexpected event", kind="unrecoverable")
    if result is None:
        raise ProviderError("Antigravity returned no terminal result", kind="unrecoverable")
    if result.get("status") != "SUCCESS":
        raise _classify_failure(str(result.get("error") or result.get("status")), 1)
    if result.get("num_turns") != 1 or not isinstance(result.get("structured_output"), dict):
        raise ProviderError("Antigravity returned no single-turn structured decision", kind="unrecoverable")
    return (
        json.dumps(result["structured_output"], ensure_ascii=False),
        json.dumps(result.get("usage") or {}),
    )


def _extract_decision_text(
    *,
    stdout: str,
    output_path: Path | None,
    output_from_stdout: bool,
) -> str:
    if output_from_stdout:
        payload = _normalize_cli_json_text(stdout)
        if not payload:
            raise ProviderError(
                "host CLI returned empty stdout",
                kind="unrecoverable",
            )
        try:
            envelope = json.loads(payload)
        except json.JSONDecodeError:
            return _coerce_json_text(payload)
        if isinstance(envelope, dict):
            structured = envelope.get("structured_output")
            if isinstance(structured, dict):
                return json.dumps(structured, ensure_ascii=False)
            result = envelope.get("result")
            if isinstance(result, str) and result.strip():
                return result.strip()
            if isinstance(result, dict):
                return json.dumps(result, ensure_ascii=False)
        return payload
    if output_path is None:
        raise ProviderError(
            "host CLI did not declare an output path",
            kind="unrecoverable",
        )
    try:
        return output_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProviderError(
            "host CLI did not materialize its final response",
            kind="unrecoverable",
        ) from exc


def _hermes_output_contract(decision_model: Any) -> str:
    """Describe only the JSON fields Hermes must produce.

    Hermes does not expose a native JSON-schema flag. The complete schema is
    enforced locally after the process exits; sending that schema through the
    Agent prompt only duplicates thousands of characters and makes small local
    models spend time reproducing nullable fields.
    """

    common = (
        "Finish this small task immediately. Return no prose outside one compact JSON "
        "object. Keep each natural-language string to one short sentence. Do not put "
        "the ASCII double quote character inside natural-language string values; "
        "paraphrase instead. Every object key and every string value must use ASCII "
        "double quotes so the result is valid JSON.parse input; never use unquoted "
        "keys, single quotes, or JavaScript object syntax. "
    )
    if decision_model is AgentExtractionDecision:
        return common + (
            'Use this shape: {"review":{"summary":"...","final_request":"...",'
            '"actual_result":"...","contradictions":[],"unfinished":[],'
            '"no_candidate_reason":null,"not_durable_signals":[]},"points":'
            '[{"kind":"memory","statement":"...","condition":null,'
            '"evidence_basis":"user_statement","report_role":null,"exchange_indexes":[1]}]}. Allowed '
            "kinds are memory, rule, relation. Use kind=memory unless you can provide "
            "a non-empty condition. Never output kind=rule without condition. "
            "A rule MUST include a non-empty condition field, for example "
            '{"kind":"rule","statement":"Do X","condition":"When Y",'
            '"evidence_basis":"user_statement","exchange_indexes":[1]}. A relation adds '
            "source_entity, target_entity, relation_type. A source_report uses kind=memory "
            "and report_role=user or assistant; other points use report_role=null. Repository evidence uses "
            "repository_locator and repository_sha256. With zero points, replace "
            "no_candidate_reason with an explanation. The only allowed "
            "not_durable_signals are exactly: user_correction, explicit_decision, "
            "successful_solution, repeated_failure, rule_or_preference, "
            "reusable_workflow_or_fact, version_or_migration, unfinished_handoff. "
            "Do not invent labels such as version_release or deletion."
        )
    if decision_model is CandidateVerificationDecision:
        return common + (
            'Use this shape: {"points":[{"candidate_index":0,'
            '"semantic_support":"supported","future_scope":"durable",'
            '"source_use":"standing_decision","scope_segments":[{"text":"exact complete claim",'
            '"source_use":"standing_decision","future_scope":"durable","standalone":true,"content_role":"claim"}],'
            '"reason":"source-based reason"}]}. Allowed semantic_support values: supported, '
            "partial, contradicted. Allowed future_scope values: durable, session_only, unclear."
            " When scope_partition_required is true, use the actual candidate's text and split "
            "claims by future use; segment texts must concatenate to scope_text when supplied, "
            "otherwise to the complete statement, exactly. Every segment includes content_role "
            "claim, qualifier, temporary_context or unclear."
        )
    if decision_model is AssimilationDecision:
        return common + (
            'Use this writing shape: {"points":[{"candidate_id":"supplied id",'
            '"disposition":"add","matched_truth_handles":[],"knowledge_items":'
            '[{"title":"short title","statement":"one fact","topic_path":'
            '["natural module"],"claim_kind":"design_requirement"}],'
            '"reason":"source-based reason"}]}. For a non-writing action, omit '
            "knowledge_items. Allowed claim_kind values: design_requirement, implementation_fact, "
            "durable_preference, procedure, source_report. Use only dispositions allowed by the task prompt."
        )
    raise TypeError(f"unsupported Hermes decision model: {decision_model!r}")


class HostStructuredCliProvider:
    """Run one schema-constrained host CLI turn in authorized agent mode."""

    def __init__(
        self,
        *,
        host_client: str,
        executable: str,
        timeout_seconds: int = 300,
        poll_seconds: float = 5.0,
    ) -> None:
        self.host_client = host_client
        self.executable = executable
        self.timeout_seconds = max(30, min(int(timeout_seconds), 900))
        self.poll_seconds = max(0.2, min(float(poll_seconds), 15.0))
        self.name = host_cli_provider_name(host_client)
        self._codex_server: Any = None
        self._native_results: list[ProviderResult] = []

    def close(self) -> dict[str, Any] | None:
        """The caller owns this executor; borrowed executors require caller close."""
        if self._codex_server is not None:
            return self._codex_server.close()
        return None

    def _run_codex(
        self, *, runtime_dir: Path, heartbeat: Any, decision_model: Any,
        prompt: str, temporary_prefix: str, error_label: str,
    ) -> ProviderResult:
        from harness_mem.autonomous.executors.codex_app_server import CodexAppServer

        started = time.monotonic()
        deadline = started + self.timeout_seconds
        record: dict[str, Any] = {}
        raw = ""
        data_dir = runtime_dir.parent.parent if runtime_dir.parent.name == "autonomous" else runtime_dir
        if self._codex_server is None:
            self._codex_server = CodexAppServer(
                self.executable, scope_factory=_invocation_process_scope,
                remove_directory=_remove_runtime_directory, poll_seconds=self.poll_seconds,
            )

        def result(decision: Any, *, valid: bool) -> ProviderResult:
            metrics = record.get("usage") or {}
            return ProviderResult(
                decision=decision, provider=self.name,
                model=(record.get("effective_profile") or {}).get("model"),
                duration_seconds=time.monotonic() - started,
                input_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                response_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                input_tokens=metrics.get("input_tokens"), output_tokens=metrics.get("output_tokens"),
                total_tokens=metrics.get("total_tokens"), event_count=int(record.get("event_count") or 0),
                schema_valid=valid, host_client="codex", native_attempts=(record,) if record else (),
            )

        try:
            with _temporary_runtime_directory(prefix=temporary_prefix, parent=runtime_dir) as cwd:
                _assert_runtime_isolated(cwd, "codex")
                env = os.environ.copy()
                env.update(HARNESS_MEM_AUTONOMOUS_PROVIDER="1", NO_COLOR="1")
                raw, record = self._codex_server.run(
                    runtime_dir=runtime_dir, data_dir=data_dir, cwd=cwd, env=env,
                    overrides=_codex_background_overrides(cwd), instructions=_CODEX_MEMORY_INSTRUCTIONS,
                    prompt=prompt, schema=_strict_output_schema(decision_model.model_json_schema()),
                    deadline=deadline, heartbeat=heartbeat,
                )
                try:
                    decision = decision_model.model_validate_json(raw)
                except (ValidationError, ValueError) as exc:
                    record["status"] = "invalid_output"
                    raise ProviderError(
                        f"codex provider returned invalid {error_label} JSON: {exc}", kind="unrecoverable",
                        failure_reason="decision_schema",
                    ) from exc
            if time.monotonic() > deadline:
                raise ProviderError("Codex call deadline exceeded during validation/cleanup", kind="transient")
            record["duration_seconds"] = time.monotonic() - started
            completed = result(decision, valid=True)
            self._native_results.append(replace(completed, decision=None))
            return completed
        except Exception as exc:
            error = exc if isinstance(exc, ProviderError) else ProviderError(str(exc), kind="transient")
            if not record and error.native_attempts:
                record = error.native_attempts[-1]
            if not record:
                record = {"call_id": uuid4().hex, "phase": "preflight", "status": "failed",
                          "model_dispatched": False, "usage": {"input_tokens": None,
                          "output_tokens": None, "total_tokens": None}}
            if record:
                record["status"] = "failed"
                record["duration_seconds"] = time.monotonic() - started
            failed = result(None, valid=False)
            self._native_results.append(failed)
            raise ProviderError(
                str(error), kind=error.kind, exit_code=error.exit_code,
                attempt_results=(*error.attempt_results, failed),
                unknown_attempt_count=error.unknown_attempt_count,
                native_attempts=(record,) if record else error.native_attempts,
                failure_reason=error.failure_reason,
            ) from exc

    def decide(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Callable[[], None] | None = None,
    ) -> ProviderResult:
        result = self._run(
            manifest,
            runtime_dir=runtime_dir,
            heartbeat=heartbeat,
            decision_model=AgentExtractionDecision,
            prompt=_build_prompt(manifest),
            temporary_prefix="distill-",
            error_label="decision",
        )
        try:
            decision = expand_agent_extraction_decision(
                result.decision,
                manifest=manifest,
            )
        except (ValidationError, ValueError) as exc:
            raise ProviderError(
                f"{self.host_client} provider decision could not be bound to local evidence: {exc}",
                kind="unrecoverable",
                attempt_results=(replace(result, schema_valid=False),) if result.native_attempts else (),
                native_attempts=result.native_attempts,
            ) from exc
        return replace(result, decision=decision)

    def verify(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Callable[[], None] | None = None,
    ) -> ProviderResult:
        return self._run(
            manifest,
            runtime_dir=runtime_dir,
            heartbeat=heartbeat,
            decision_model=CandidateVerificationDecision,
            prompt=_build_verification_prompt(manifest),
            temporary_prefix="verification-",
            error_label="verification",
        )

    def assimilate(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Callable[[], None] | None = None,
    ) -> ProviderResult:
        return self._run(
            manifest,
            runtime_dir=runtime_dir,
            heartbeat=heartbeat,
            decision_model=AssimilationDecision,
            prompt=_build_assimilation_prompt(manifest),
            temporary_prefix="assimilation-",
            error_label="assimilation",
        )

    def _run(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Callable[[], None] | None,
        decision_model: Any,
        prompt: str,
        temporary_prefix: str,
        error_label: str,
    ) -> ProviderResult:
        del manifest
        if not self.executable:
            raise ProviderError(
                f"{self.host_client} CLI executable was not found",
                kind="setup_required",
            )
        runtime_dir.mkdir(parents=True, exist_ok=True)
        if self.host_client == "codex":
            return self._run_codex(
                runtime_dir=runtime_dir, heartbeat=heartbeat, decision_model=decision_model,
                prompt=prompt, temporary_prefix=temporary_prefix, error_label=error_label,
            )
        started = time.monotonic()
        with _temporary_runtime_directory(
            prefix=temporary_prefix,
            parent=runtime_dir,
        ) as invocation_dir:
            execution_cwd = invocation_dir
            if self.host_client == "hermes":
                execution_cwd = runtime_dir / "hermes-cwd"
                execution_cwd.mkdir(parents=True, exist_ok=True)
            _assert_runtime_isolated(execution_cwd, self.host_client)
            if self.host_client == "antigravity":
                _write_antigravity_worker(execution_cwd)
            schema_path = invocation_dir / "decision.schema.json"
            output_path = invocation_dir / "decision.json"
            usage_path = invocation_dir / "usage.json"
            schema_path.write_text(
                json.dumps(
                    _strict_output_schema(decision_model.model_json_schema()),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            cli_prompt = prompt
            if self.host_client == "hermes":
                cli_prompt = f"{prompt}\n\n{_hermes_output_contract(decision_model)}"
            invocation = _build_host_invocation(
                host_client=self.host_client,
                executable=self.executable,
                schema_path=schema_path,
                output_path=output_path,
                prompt=cli_prompt,
                usage_path=usage_path,
            )
            if self.host_client == "codex":
                instructions_path = invocation_dir / "instructions.md"
                instructions_path.write_text(
                    "You are the harness-mem memory decision worker. Use only the supplied "
                    "task and evidence. Do not call tools, inspect the host, or execute actions. "
                    "Return only the requested JSON decision; the runtime verifies evidence "
                    "and owns all memory writes.", encoding="utf-8",
                )
                invocation = replace(
                    invocation,
                    command=[
                        *invocation.command[:-1],
                        *_codex_background_overrides(execution_cwd),
                        "-c", "model_instructions_file=" + json.dumps(str(instructions_path)),
                        "-",
                    ],
                )
            env = os.environ.copy()
            env.update(invocation.env)
            env["HARNESS_MEM_AUTONOMOUS_PROVIDER"] = "1"
            env["NO_COLOR"] = "1"
            if self.host_client == "hermes":
                env["HERMES_SESSION_SOURCE"] = "tool"
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            data_dir = (
                runtime_dir.parent.parent
                if runtime_dir.parent.name == "autonomous"
                else runtime_dir
            )
            with ExitStack() as streams:
                # A completed Windows CLI can leave children holding pipe handles.
                # Wait for the CLI's exit, not EOF from those unrelated children.
                captured_stdout = captured_stderr = None
                if self.host_client in {"codex", "antigravity"}:
                    captured_stdout = streams.enter_context(
                        tempfile.TemporaryFile(
                            mode="w+", encoding="utf-8", errors="replace"
                        )
                    )
                    captured_stderr = streams.enter_context(
                        tempfile.TemporaryFile(
                            mode="w+", encoding="utf-8", errors="replace"
                        )
                    )
                provider_lease = register_provider_process_lease(
                    data_dir,
                    pid=os.getpid(),
                )
                try:
                    stdout, stderr, process_returncode = self._communicate(
                        invocation,
                        execution_cwd,
                        env,
                        creationflags,
                        cli_prompt,
                        started,
                        heartbeat,
                        captured_stdout,
                        captured_stderr,
                    )
                finally:
                    release_provider_process_lease(provider_lease)

                if captured_stdout is not None and captured_stderr is not None:
                    captured_stdout.seek(0)
                    captured_stderr.seek(0)
                    stdout, stderr = captured_stdout.read(), captured_stderr.read()

            if process_returncode != 0:
                raise _classify_failure(stderr or stdout, process_returncode)

            if self.host_client == "codex":
                _reject_codex_tool_activity(stdout)

            usage_text = ""
            try:
                if self.host_client == "antigravity":
                    raw, usage_text = _extract_antigravity_result(stdout)
                else:
                    raw = _extract_decision_text(
                        stdout=stdout,
                        output_path=invocation.output_path,
                        output_from_stdout=invocation.output_from_stdout,
                    )
            except ProviderError as exc:
                detail = (stderr or stdout or "").strip()
                if detail:
                    if _reported_cli_failure(detail):
                        raise _classify_failure(
                            detail, process_returncode or 1
                        ) from exc
                    raise ProviderError(
                        f"{exc}; stderr/stdout sample: {detail[:500]}",
                        kind=exc.kind,
                        failure_reason="decision_schema",
                    ) from exc
                raise
            try:
                decision = decision_model.model_validate_json(raw)
            except (ValidationError, ValueError) as exc:
                raise ProviderError(
                    f"{self.host_client} provider returned invalid {error_label} JSON: {exc}",
                    kind="unrecoverable",
                    exit_code=process_returncode,
                    failure_reason="decision_schema",
                ) from exc

            if self.host_client == "hermes":
                try:
                    usage_text = usage_path.read_text(encoding="utf-8")
                except OSError:
                    pass

        metrics = _usage_metrics(usage_text or stdout)
        return ProviderResult(
            decision=decision,
            provider=self.name,
            model=None,
            duration_seconds=time.monotonic() - started,
            input_sha256=hashlib.sha256(cli_prompt.encode("utf-8")).hexdigest(),
            response_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            input_tokens=metrics["input_tokens"],
            output_tokens=metrics["output_tokens"],
            total_tokens=metrics["total_tokens"],
            event_count=int(metrics["event_count"] or 0),
            host_client=self.host_client,
        )

    def _communicate(
        self,
        invocation: _CliInvocation,
        execution_cwd: Path,
        env: dict[str, str],
        creationflags: int,
        cli_prompt: str,
        started: float,
        heartbeat: Callable[[], None] | None,
        captured_stdout: Any,
        captured_stderr: Any,
    ) -> tuple[str, str, int]:
        try:
            process = subprocess.Popen(
                invocation.command,
                cwd=execution_cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=captured_stdout
                if captured_stdout is not None
                else subprocess.PIPE,
                stderr=captured_stderr
                if captured_stderr is not None
                else subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags | (
                    0x00000004  # CREATE_SUSPENDED; join the scope before startup.
                    if self.host_client in {"codex", "antigravity"} and os.name == "nt"
                    else 0
                ),
            )
        except OSError as exc:
            raise ProviderError(str(exc), kind="setup_required") from exc

        try:
            if self.host_client in {"hermes", "antigravity"} and os.name == "nt" and process.stdin is not None:
                # Keep the source packet byte-for-byte UTF-8 on the pipe;
                # Windows text-mode newline expansion would change its hashes.
                process.stdin.reconfigure(newline="\n")
            with _invocation_process_scope(
                process, enabled=self.host_client in {"codex", "antigravity"},
            ):
                return self._wait_for_cli(
                    process,
                    invocation.stdin_text if invocation.stdin_text is not None else cli_prompt,
                    started, heartbeat,
                )
        except (OSError, AttributeError) as exc:
            _terminate_process_tree(process)
            raise ProviderError(
                f"Cannot initialize {self.host_client} stdin/process containment",
                kind="setup_required",
            ) from exc

    def _wait_for_cli(
        self,
        process: subprocess.Popen[str],
        cli_prompt: str,
        started: float,
        heartbeat: Callable[[], None] | None,
    ) -> tuple[str, str, int]:
        deadline = started + self.timeout_seconds
        first_communicate = True
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_tree(process)
                raise ProviderError(
                    f"{self.host_client} provider exceeded {self.timeout_seconds}s",
                    kind="transient",
                )
            try:
                stdout, stderr = process.communicate(
                    input=(
                        cli_prompt
                        if first_communicate and (
                            self.host_client != "hermes" or os.name == "nt"
                        )
                        else None
                    ),
                    timeout=min(self.poll_seconds, remaining),
                )
                return stdout or "", stderr or "", process.returncode
            except subprocess.TimeoutExpired:
                first_communicate = False
                if heartbeat is not None:
                    heartbeat()
