"""Structured host CLI invocations for authorized background agent mode."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any, Callable, Mapping

from pydantic import ValidationError

from harness_mem.autonomous.models import (
    AssimilationDecision,
    AutonomousDecision,
    CandidateVerificationDecision,
)
from harness_mem.autonomous.provider import (
    DEFAULT_ASSIMILATION_MODEL,
    ProviderError,
    ProviderResult,
    _agent_boundary_fields,
    _build_assimilation_prompt,
    _build_prompt,
    _build_verification_prompt,
    _classify_failure,
    _prepare_isolated_codex_home,
    _strict_output_schema,
    _usage_metrics,
)
from harness_mem.autonomous.executors.constants import host_cli_provider_name
from harness_mem.config.merge import MergedConfig

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


def _build_codex_like_command(
    *,
    executable: str,
    schema_path: Path,
    output_path: Path,
    model: str | None,
    agent_mode: bool,
) -> _CliInvocation:
    command = [executable, "exec", "--ephemeral"]
    if not agent_mode:
        command.extend(
            [
                "--ignore-rules",
                "--disable",
                "hooks",
                "--disable",
                "plugins",
                "--disable",
                "skill_search",
                "--disable",
                "multi_agent",
                "--config",
                "mcp_servers={}",
                "--config",
                "marketplaces={}",
            ]
        )
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
    if model:
        command.extend(("--model", model))
    command.append("-")
    return _CliInvocation(command=command, env={}, output_path=output_path)


def _build_claude_code_command(
    *,
    executable: str,
    schema_path: Path,
    model: str | None,
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
    if model:
        command.extend(("--model", model))
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
    model: str | None,
) -> _CliInvocation:
    command = [
        executable,
        "chat",
        "-Q",
        "--accept-hooks",
        "--yolo",
        "--query-file",
        "-",
    ]
    if model:
        command.extend(["-m", model])
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
    model: str | None,
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
    if model:
        command.extend(("--model", model))
    command.append("-")
    return _CliInvocation(command=command, env={}, output_path=output_path)


def _build_host_invocation(
    *,
    host_client: str,
    executable: str,
    schema_path: Path,
    output_path: Path,
    model: str | None,
    agent_mode: bool,
    isolated_home: Path | None,
) -> _CliInvocation:
    if host_client == "codex":
        invocation = _build_codex_like_command(
            executable=executable,
            schema_path=schema_path,
            output_path=output_path,
            model=model,
            agent_mode=agent_mode,
        )
        env = dict(invocation.env)
        if isolated_home is not None:
            env["CODEX_HOME"] = str(isolated_home)
        return _CliInvocation(
            command=invocation.command,
            env=env,
            output_path=invocation.output_path,
            output_from_stdout=invocation.output_from_stdout,
        )
    if host_client == "claude-code":
        return _build_claude_code_command(
            executable=executable,
            schema_path=schema_path,
            model=model,
        )
    if host_client == "hermes":
        return _build_hermes_command(
            executable=executable,
            model=model,
        )
    if host_client == "opencode":
        return _build_opencode_command(
            executable=executable,
            schema_path=schema_path,
            output_path=output_path,
            model=model,
        )
    raise ProviderError(
        f"unsupported host client for structured CLI: {host_client}",
        kind="setup_required",
    )


def _coerce_json_text(raw: str) -> str:
    payload = raw.strip()
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
            json.loads(candidate)
            return candidate
        raise


def _extract_decision_text(
    *,
    stdout: str,
    output_path: Path | None,
    output_from_stdout: bool,
) -> str:
    if output_from_stdout:
        payload = stdout.strip()
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


class HostStructuredCliProvider:
    """Run one schema-constrained host CLI turn in authorized agent mode."""

    def __init__(
        self,
        *,
        host_client: str,
        executable: str,
        config: MergedConfig,
        timeout_seconds: int = 180,
        poll_seconds: float = 5.0,
    ) -> None:
        self.host_client = host_client
        self.executable = executable
        self.config = config
        self.timeout_seconds = max(30, min(int(timeout_seconds), 900))
        self.poll_seconds = max(0.2, min(float(poll_seconds), 15.0))
        self.name = host_cli_provider_name(host_client)
        self.model = (os.environ.get("HARNESS_MEM_DISTILL_MODEL") or "").strip() or None
        self.assimilation_model = (
            os.environ.get("HARNESS_MEM_ASSIMILATION_MODEL")
            or DEFAULT_ASSIMILATION_MODEL
        ).strip()

    def decide(
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
            decision_model=AutonomousDecision,
            prompt=_build_prompt(manifest),
            temporary_prefix="distill-",
            error_label="decision",
        )

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
            model=self.assimilation_model,
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
        model: str | None = None,
    ) -> ProviderResult:
        del manifest
        if not self.executable:
            raise ProviderError(
                f"{self.host_client} CLI executable was not found",
                kind="setup_required",
            )
        runtime_dir.mkdir(parents=True, exist_ok=True)
        _assert_runtime_isolated(runtime_dir, self.host_client)
        started = time.monotonic()
        selected_model = model or self.model
        with tempfile.TemporaryDirectory(
            prefix=temporary_prefix, dir=runtime_dir
        ) as temporary:
            invocation_dir = Path(temporary)
            schema_path = invocation_dir / "decision.schema.json"
            output_path = invocation_dir / "decision.json"
            schema_path.write_text(
                json.dumps(
                    _strict_output_schema(decision_model.model_json_schema()),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            isolated_home: Path | None = None
            configured_model = selected_model
            if self.host_client == "codex":
                isolated_home, configured_model = _prepare_isolated_codex_home(
                    invocation_dir
                )
                if selected_model is None and configured_model:
                    selected_model = configured_model
            invocation = _build_host_invocation(
                host_client=self.host_client,
                executable=self.executable,
                schema_path=schema_path,
                output_path=output_path,
                model=selected_model,
                agent_mode=True,
                isolated_home=isolated_home,
            )
            cli_prompt = prompt
            if self.host_client == "hermes":
                cli_prompt = (
                    f"{prompt}\n\nRespond with JSON only that validates against "
                    f"this schema:\n{schema_path.read_text(encoding='utf-8')}"
                )
            env = os.environ.copy()
            env.update(invocation.env)
            env["HARNESS_MEM_AUTONOMOUS_PROVIDER"] = "1"
            env["NO_COLOR"] = "1"
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            try:
                process = subprocess.Popen(
                    invocation.command,
                    cwd=runtime_dir,
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
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise ProviderError(
                        f"{self.host_client} provider exceeded {self.timeout_seconds}s",
                        kind="transient",
                    )
                try:
                    stdout, stderr = process.communicate(
                        input=cli_prompt if first_communicate else None,
                        timeout=min(self.poll_seconds, remaining),
                    )
                    break
                except subprocess.TimeoutExpired:
                    first_communicate = False
                    if heartbeat is not None:
                        heartbeat()

            if process.returncode != 0:
                raise _classify_failure(stderr or stdout, process.returncode)

            raw = _extract_decision_text(
                stdout=stdout,
                output_path=invocation.output_path,
                output_from_stdout=invocation.output_from_stdout,
            )
            try:
                decision = decision_model.model_validate_json(raw)
            except (ValidationError, ValueError) as exc:
                raise ProviderError(
                    f"{self.host_client} provider returned invalid {error_label} JSON: {exc}",
                    kind="unrecoverable",
                    exit_code=process.returncode,
                ) from exc

        metrics = _usage_metrics(stdout)
        return ProviderResult(
            decision=decision,
            provider=self.name,
            model=selected_model or configured_model,
            duration_seconds=time.monotonic() - started,
            input_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            response_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            input_tokens=metrics["input_tokens"],
            output_tokens=metrics["output_tokens"],
            total_tokens=metrics["total_tokens"],
            event_count=int(metrics["event_count"] or 0),
            **_agent_boundary_fields(
                execution_mode="agent",
                host_client=self.host_client,
            ),
        )
