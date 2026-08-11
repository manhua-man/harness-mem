"""Restricted non-interactive Codex provider for semantic distillation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import ValidationError
import tomli_w

from harness_mem.autonomous.models import AutonomousDecision


@dataclass(frozen=True)
class ProviderResult:
    decision: AutonomousDecision
    provider: str
    model: str | None
    duration_seconds: float
    input_sha256: str
    response_sha256: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    event_count: int
    attempt_count: int = 1
    schema_valid: bool = True
    sandbox: str = "read-only"
    ephemeral: bool = True
    cwd_isolated: bool = True
    hooks_disabled: bool = True
    plugins_disabled: bool = True
    mcp_disabled: bool = True
    rules_ignored: bool = True
    config_isolated: bool = True

    def receipt(self) -> dict[str, Any]:
        return {
            "name": self.provider,
            "model": self.model,
            "duration_seconds": round(self.duration_seconds, 3),
            "input_sha256": self.input_sha256,
            "response_sha256": self.response_sha256,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "event_count": self.event_count,
            "attempt_count": self.attempt_count,
            "schema_valid": self.schema_valid,
            "sandbox": self.sandbox,
            "ephemeral": self.ephemeral,
            "cwd_isolated": self.cwd_isolated,
            "hooks_disabled": self.hooks_disabled,
            "plugins_disabled": self.plugins_disabled,
            "mcp_disabled": self.mcp_disabled,
            "rules_ignored": self.rules_ignored,
            "config_isolated": self.config_isolated,
        }


class ProviderError(RuntimeError):
    """Stable failure classification for retry and health reporting."""

    def __init__(self, message: str, *, kind: str, exit_code: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.exit_code = exit_code


class CodexExecProvider:
    """Run one schema-constrained Codex turn in a neutral read-only cwd."""

    name = "codex_exec"

    def __init__(
        self,
        *,
        executable: str | None = None,
        model: str | None = None,
        timeout_seconds: int = 180,
        poll_seconds: float = 5.0,
    ) -> None:
        self.executable = executable or shutil.which("codex") or ""
        self.model = (model or os.environ.get("HARNESS_MEM_DISTILL_MODEL") or "").strip() or None
        self.timeout_seconds = max(30, min(int(timeout_seconds), 900))
        self.poll_seconds = max(0.2, min(float(poll_seconds), 15.0))

    def decide(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Callable[[], None] | None = None,
    ) -> ProviderResult:
        if not self.executable:
            raise ProviderError("Codex CLI executable was not found", kind="setup_required")
        runtime_dir.mkdir(parents=True, exist_ok=True)
        if (runtime_dir / ".codex" / "hooks.json").exists():
            raise ProviderError(
                "autonomous provider cwd contains a Codex hook manifest",
                kind="setup_required",
            )

        prompt = _build_prompt(manifest)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="distill-", dir=runtime_dir) as temporary:
            invocation_dir = Path(temporary)
            schema_path = invocation_dir / "decision.schema.json"
            output_path = invocation_dir / "decision.json"
            schema_path.write_text(
                json.dumps(
                    _strict_output_schema(AutonomousDecision.model_json_schema()),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            isolated_home, configured_model = _prepare_isolated_codex_home(
                invocation_dir
            )
            command = [
                self.executable,
                "exec",
                "--ephemeral",
                "--ignore-rules",
                "--disable",
                "hooks",
                "--disable",
                "plugins",
                "--disable",
                "skill_search",
                "--disable",
                "multi_agent",
                "--skip-git-repo-check",
                "--config",
                "mcp_servers={}",
                "--config",
                "marketplaces={}",
                "--sandbox",
                "read-only",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "--json",
            ]
            if self.model:
                command.extend(("--model", self.model))
            command.append("-")
            env = os.environ.copy()
            env["CODEX_HOME"] = str(isolated_home)
            env["HARNESS_MEM_AUTONOMOUS_PROVIDER"] = "1"
            env["NO_COLOR"] = "1"
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            try:
                process = subprocess.Popen(
                    command,
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
                        f"Codex provider exceeded {self.timeout_seconds}s",
                        kind="transient",
                    )
                try:
                    stdout, stderr = process.communicate(
                        input=prompt if first_communicate else None,
                        timeout=min(self.poll_seconds, remaining),
                    )
                    break
                except subprocess.TimeoutExpired:
                    first_communicate = False
                    if heartbeat is not None:
                        heartbeat()

            if process.returncode != 0:
                raise _classify_failure(stderr or stdout, process.returncode)
            try:
                raw = output_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise ProviderError(
                    "Codex provider did not materialize its final response",
                    kind="unrecoverable",
                    exit_code=process.returncode,
                ) from exc
            try:
                decision = AutonomousDecision.model_validate_json(raw)
            except (ValidationError, ValueError) as exc:
                raise ProviderError(
                    f"Codex provider returned invalid decision JSON: {exc}",
                    kind="unrecoverable",
                    exit_code=process.returncode,
                ) from exc

        metrics = _usage_metrics(stdout)
        return ProviderResult(
            decision=decision,
            provider=self.name,
            model=self.model or configured_model,
            duration_seconds=time.monotonic() - started,
            input_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            response_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            input_tokens=metrics["input_tokens"],
            output_tokens=metrics["output_tokens"],
            total_tokens=metrics["total_tokens"],
            event_count=metrics["event_count"],
        )


class ResponsesApiProvider:
    """Call the configured Responses endpoint directly with no Agent tools."""

    name = "responses_api"

    def __init__(
        self,
        *,
        model: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.model = (model or os.environ.get("HARNESS_MEM_DISTILL_MODEL") or "").strip() or None
        self.timeout_seconds = max(30, min(int(timeout_seconds), 300))

    def decide(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Callable[[], None] | None = None,
    ) -> ProviderResult:
        del runtime_dir
        endpoint, headers, configured_model = _configured_responses_endpoint()
        model = self.model or configured_model
        if not model:
            raise ProviderError("No model is configured for autonomous distill", kind="setup_required")
        prompt = _build_prompt(manifest)
        schema = _strict_output_schema(AutonomousDecision.model_json_schema())
        request_payload = {
            "model": model,
            "input": prompt,
            "reasoning": {"effort": "low"},
            "text": {
                "verbosity": "low",
                "format": {
                    "type": "json_schema",
                    "name": "harness_mem_distill",
                    "strict": True,
                    "schema": schema,
                },
            },
            "tools": [],
            "store": False,
            "max_output_tokens": 4000,
        }
        encoded = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=encoded,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        if heartbeat is not None:
            heartbeat()
        started = time.monotonic()
        try:
            with urllib.request.urlopen(  # noqa: S310 - configured trusted endpoint.
                request,
                timeout=self.timeout_seconds,
            ) as response:
                raw_response = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise _classify_failure(body or str(exc), int(exc.code)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(str(exc), kind="transient") from exc
        if heartbeat is not None:
            heartbeat()
        try:
            payload = json.loads(raw_response)
            output_text = _responses_output_text(payload)
            decision = AutonomousDecision.model_validate_json(output_text)
        except (json.JSONDecodeError, ValidationError, ValueError, KeyError) as exc:
            raise ProviderError(
                f"Responses provider returned invalid decision JSON: {exc}",
                kind="unrecoverable",
            ) from exc
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return ProviderResult(
            decision=decision,
            provider=self.name,
            model=str(payload.get("model") or model),
            duration_seconds=time.monotonic() - started,
            input_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            response_sha256=hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
            input_tokens=_integer_or_none(usage.get("input_tokens")),
            output_tokens=_integer_or_none(usage.get("output_tokens")),
            total_tokens=_integer_or_none(usage.get("total_tokens")),
            event_count=len(payload.get("output") or []),
            sandbox="no-tools",
        )


def _build_prompt(manifest: dict[str, Any]) -> str:
    packet = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
    return (
        "You are the restricted semantic reviewer for harness-mem. Review the complete "
        "indexed session manifest below. Return only the JSON object required by the "
        "provided schema. Do not call tools, inspect the filesystem, or infer repository "
        "facts that are not in the manifest. A session summary is always required and "
        "must explain the user's request, actual outcome, and unfinished work. Produce "
        "durable candidates only for stable, future-useful facts, decisions, preferences, "
        "rules, or relations. One candidate must express one verifiable fact. For a "
        "memory candidate, category, content, and confidence are required. For a "
        "rule candidate, pattern and trigger are required. For a relation candidate, "
        "source_entity, target_entity, relation_type, evidence, and confidence are "
        "required. "
        "user_statement candidate, cite an inspected exchange hash and role=user. Raw "
        "transcript evidence cannot verify a durable repository fact. If there are no "
        "candidates, copy the supplied zero-candidate template and replace its checks, "
        "future_utility, conclusion, and rationale with your evidence-grounded decision. "
        "Name every downgraded detected signal in the rationale. Never claim completion "
        "when the final turn or evidence is unfinished.\n\n"
        f"<distill_manifest>{packet}</distill_manifest>"
    )


def _strict_output_schema(value: Any) -> Any:
    """Compile Pydantic JSON Schema to the strict Structured Output subset."""

    if isinstance(value, list):
        return [_strict_output_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    compiled = {
        key: _strict_output_schema(item)
        for key, item in value.items()
        if key not in {"default"}
    }
    properties = compiled.get("properties")
    if isinstance(properties, dict):
        compiled["additionalProperties"] = False
        compiled["required"] = list(properties)
    return compiled


def _prepare_isolated_codex_home(invocation_dir: Path) -> tuple[Path, str | None]:
    """Copy only provider/auth essentials into an ephemeral Codex home."""

    source_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    source_config = source_home / "config.toml"
    try:
        config = tomllib.loads(source_config.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        config = {}
    provider_name = str(config.get("model_provider") or "").strip()
    providers = config.get("model_providers")
    provider_table = (
        providers.get(provider_name)
        if provider_name and isinstance(providers, dict)
        else None
    )
    minimal: dict[str, Any] = {}
    for key in ("model", "model_catalog_json", "service_tier"):
        if key in config:
            minimal[key] = config[key]
    catalog = minimal.get("model_catalog_json")
    if isinstance(catalog, str) and catalog and not Path(catalog).is_absolute():
        minimal["model_catalog_json"] = str((source_home / catalog).resolve())
    # Semantic compression does not need a coding agent's deep reasoning level.
    minimal["model_reasoning_effort"] = "low"
    if provider_name and isinstance(provider_table, dict):
        minimal["model_provider"] = provider_name
        minimal["model_providers"] = {provider_name: provider_table}
    minimal["sandbox_mode"] = "read-only"
    minimal["features"] = {
        "hooks": False,
        "plugins": False,
        "skill_search": False,
        "multi_agent": False,
        "memories": False,
    }
    isolated_home = invocation_dir / "codex-home"
    isolated_home.mkdir(parents=True, exist_ok=True)
    (isolated_home / "config.toml").write_text(
        tomli_w.dumps(minimal),
        encoding="utf-8",
    )
    source_auth = source_home / "auth.json"
    if source_auth.is_file():
        target_auth = isolated_home / "auth.json"
        try:
            os.link(source_auth, target_auth)
        except OSError:
            # A copy is confined to TemporaryDirectory and removed after the turn.
            shutil.copyfile(source_auth, target_auth)
    return isolated_home, str(minimal.get("model") or "").strip() or None


def _configured_responses_endpoint() -> tuple[str, dict[str, str], str | None]:
    source_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        config = tomllib.loads(
            (source_home / "config.toml").read_text(encoding="utf-8")
        )
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProviderError("Codex provider configuration is unavailable", kind="setup_required") from exc
    provider_name = str(config.get("model_provider") or "").strip()
    providers = config.get("model_providers")
    provider = (
        providers.get(provider_name)
        if provider_name and isinstance(providers, dict)
        else None
    )
    if not isinstance(provider, dict):
        raise ProviderError("Active Codex model provider is unavailable", kind="setup_required")
    base_url = str(provider.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        raise ProviderError("Active Codex provider has no base_url", kind="setup_required")
    headers = {
        str(key): str(value)
        for key, value in dict(provider.get("http_headers") or {}).items()
    }
    token = str(provider.get("experimental_bearer_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif bool(provider.get("requires_openai_auth")):
        api_key = str(os.environ.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise ProviderError(
                "The active provider requires OPENAI_API_KEY for background use",
                kind="auth_invalid",
            )
        headers["Authorization"] = f"Bearer {api_key}"
    return (
        f"{base_url}/responses",
        headers,
        str(config.get("model") or "").strip() or None,
    )


def _responses_output_text(payload: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                texts.append(str(content.get("text") or ""))
    text = "\n".join(part for part in texts if part).strip()
    if not text:
        raise ValueError("response contains no output_text")
    return text


def _integer_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and value >= 0 else None


def _classify_failure(output: str, exit_code: int) -> ProviderError:
    text = output.strip()[-2000:]
    lowered = text.lower()
    if any(marker in lowered for marker in ("not logged in", "authentication", "unauthorized", "invalid api key")):
        kind = "auth_invalid"
    elif any(marker in lowered for marker in ("quota", "usage limit", "rate limit")):
        kind = "quota_exhausted"
    elif any(marker in lowered for marker in ("prompt is too long", "context window")):
        kind = "unrecoverable"
    elif any(marker in lowered for marker in ("not found", "enoent", "unknown option")):
        kind = "setup_required"
    else:
        kind = "transient"
    return ProviderError(
        text or f"Codex provider exited with {exit_code}",
        kind=kind,
        exit_code=exit_code,
    )


def _usage_metrics(stdout: str) -> dict[str, int | None]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    values: dict[str, list[int]] = {
        "input_tokens": [],
        "output_tokens": [],
        "total_tokens": [],
    }

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in values and isinstance(item, int) and item >= 0:
                    values[key].append(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for event in events:
        walk(event)
    input_tokens = max(values["input_tokens"], default=None)
    output_tokens = max(values["output_tokens"], default=None)
    total_tokens = max(values["total_tokens"], default=None)
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "event_count": len(events),
    }


__all__ = [
    "CodexExecProvider",
    "ResponsesApiProvider",
    "ProviderError",
    "ProviderResult",
    "_strict_output_schema",
    "_prepare_isolated_codex_home",
]
