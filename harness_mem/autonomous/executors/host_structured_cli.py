"""Structured host CLI invocations for authorized background agent mode."""

from __future__ import annotations

from contextlib import contextmanager
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

_HOOK_GUARD_CHECKS: dict[str, tuple[str, ...]] = {
    "codex": (".codex", "hooks.json"),
    "claude-code": (".claude", "hooks"),
    "opencode": (".opencode", "plugins", "harness-mem.ts"),
}


@dataclass(frozen=True)
class _CliInvocation:
    command: list[str]
    env: Mapping[str, str]
    output_path: Path | None
    output_from_stdout: bool = False


@contextmanager
def _temporary_runtime_directory(*, prefix: str, parent: Path) -> Iterator[Path]:
    """Remove an invocation directory after short-lived Windows children exit."""

    path = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    try:
        yield path
    finally:
        for attempt in range(40):
            try:
                shutil.rmtree(path)
                break
            except FileNotFoundError:
                break
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
        return process.communicate(timeout=10)
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
        start = payload.find("{")
        end = payload.rfind("}")
        if start >= 0 and end > start:
            candidate = payload[start : end + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    f"host CLI returned non-JSON output: {payload[:500]}",
                    kind="unrecoverable",
                ) from exc
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
        "paraphrase instead. "
    )
    if decision_model is AgentExtractionDecision:
        return common + (
            'Use this shape: {"review":{"summary":"...","final_request":"...",'
            '"actual_result":"...","contradictions":[],"unfinished":[],'
            '"no_candidate_reason":null,"not_durable_signals":[]},"points":'
            '[{"kind":"memory","statement":"...","evidence_basis":"user_statement",'
            '"exchange_indexes":[1]}]}. Allowed kinds are memory, rule, relation. A rule adds '
            "condition. A relation adds source_entity, target_entity, relation_type. Repository "
            "evidence uses repository_locator and repository_sha256. With zero points, replace "
            "no_candidate_reason with an explanation."
        )
    if decision_model is CandidateVerificationDecision:
        return common + (
            'Use this shape: {"points":[{"candidate_index":0,'
            '"semantic_support":"supported","future_scope":"durable",'
            '"reason":"source-based reason"}]}. Allowed semantic_support values: supported, '
            "partial, contradicted. Allowed future_scope values: durable, session_only, unclear."
        )
    if decision_model is AssimilationDecision:
        return common + (
            'Use this writing shape: {"points":[{"candidate_id":"supplied id",'
            '"disposition":"add","matched_truth_handles":[],"knowledge_items":'
            '[{"title":"short title","statement":"one fact","topic_path":'
            '["natural module"],"claim_kind":"design_requirement"}],'
            '"reason":"source-based reason"}]}. For a non-writing action, omit '
            "knowledge_items. Allowed claim_kind values: design_requirement, implementation_fact, "
            "durable_preference, procedure. Use only dispositions allowed by the task prompt."
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
            provider_lease = register_provider_process_lease(
                data_dir,
                pid=os.getpid(),
            )
            try:
                try:
                    process = subprocess.Popen(
                        invocation.command,
                        cwd=execution_cwd,
                        env=env,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        creationflags=creationflags,
                    )
                except OSError as exc:
                    raise ProviderError(str(exc), kind="setup_required") from exc

                stdout = ""
                stderr = ""
                deadline = started + self.timeout_seconds
                first_communicate = True
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        stdout, stderr = _terminate_process_tree(process)
                        raise ProviderError(
                            f"{self.host_client} provider exceeded {self.timeout_seconds}s",
                            kind="transient",
                        )
                    try:
                        stdout, stderr = process.communicate(
                            input=(
                                cli_prompt
                                if first_communicate and self.host_client != "hermes"
                                else None
                            ),
                            timeout=min(self.poll_seconds, remaining),
                        )
                        break
                    except subprocess.TimeoutExpired:
                        first_communicate = False
                        if heartbeat is not None:
                            heartbeat()
            finally:
                release_provider_process_lease(provider_lease)

            if process.returncode != 0:
                raise _classify_failure(stderr or stdout, process.returncode)

            try:
                raw = _extract_decision_text(
                    stdout=stdout,
                    output_path=invocation.output_path,
                    output_from_stdout=invocation.output_from_stdout,
                )
            except ProviderError as exc:
                detail = (stderr or stdout or "").strip()
                if detail:
                    if _reported_cli_failure(detail):
                        raise _classify_failure(detail, process.returncode or 1) from exc
                    raise ProviderError(
                        f"{exc}; stderr/stdout sample: {detail[:500]}",
                        kind=exc.kind,
                    ) from exc
                raise
            try:
                decision = decision_model.model_validate_json(raw)
            except (ValidationError, ValueError) as exc:
                raise ProviderError(
                    f"{self.host_client} provider returned invalid {error_label} JSON: {exc}",
                    kind="unrecoverable",
                    exit_code=process.returncode,
                ) from exc

            usage_text = ""
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
