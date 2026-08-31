#!/usr/bin/env python3
"""Probe real host CLIs for structured autonomous executor compatibility."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

MIN_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
MIN_PROMPT = 'Return JSON only: {"ok": true}'


@dataclass(frozen=True)
class SmokeResult:
    host_client: str
    executable: str
    status: str
    command: list[str]
    detail: str
    output_sample: str = ""


def _resolve_executable(host_client: str) -> str:
    defaults = {
        "codex": ("codex", "HARNESS_MEM_CODEX_EXECUTABLE"),
        "claude-code": ("claude", "HARNESS_MEM_CLAUDE_EXECUTABLE"),
        "hermes": ("hermes", "HARNESS_MEM_HERMES_EXECUTABLE"),
        "opencode": ("opencode", "HARNESS_MEM_OPENCODE_EXECUTABLE"),
    }
    default_name, env_name = defaults[host_client]
    configured = str(os.environ.get(env_name) or "").strip()
    if configured:
        return configured
    return shutil.which(default_name) or ""


def _run_probe(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdin: str,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        input=stdin,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )


def _probe_codex(executable: str, *, invoke: bool, timeout_seconds: int) -> SmokeResult:
    command_base = [
        executable,
        "exec",
        "--help",
    ]
    help_proc = _run_probe(
        command_base,
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        stdin="",
        timeout_seconds=30,
    )
    if help_proc.returncode != 0:
        return SmokeResult(
            host_client="codex",
            executable=executable,
            status="blocked",
            command=command_base,
            detail=(help_proc.stderr or help_proc.stdout or "exec --help failed").strip(),
        )
    help_text = help_proc.stdout
    for flag in ("--output-schema", "--output-last-message", "--ephemeral"):
        if flag not in help_text:
            return SmokeResult(
                host_client="codex",
                executable=executable,
                status="blocked",
                command=command_base,
                detail=f"missing required flag: {flag}",
            )
    if not invoke:
        return SmokeResult(
            host_client="codex",
            executable=executable,
            status="probe_only",
            command=command_base,
            detail="help verified structured exec flags",
        )

    with tempfile.TemporaryDirectory(prefix="hm-smoke-codex-") as temporary:
        work = Path(temporary)
        schema_path = work / "schema.json"
        output_path = work / "out.json"
        schema_path.write_text(json.dumps(MIN_SCHEMA), encoding="utf-8")
        command = [
            executable,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "--json",
            "-",
        ]
        env = os.environ.copy()
        env["HARNESS_MEM_AUTONOMOUS_PROVIDER"] = "1"
        env["NO_COLOR"] = "1"
        proc = _run_probe(
            command,
            cwd=work,
            env=env,
            stdin=MIN_PROMPT,
            timeout_seconds=timeout_seconds,
        )
        if proc.returncode != 0:
            return SmokeResult(
                host_client="codex",
                executable=executable,
                status="failed",
                command=command,
                detail=(proc.stderr or proc.stdout or "non-zero exit").strip()[:500],
            )
        if not output_path.is_file():
            return SmokeResult(
                host_client="codex",
                executable=executable,
                status="failed",
                command=command,
                detail="structured output file missing",
                output_sample=(proc.stdout or "")[:500],
            )
        raw = output_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        if payload.get("ok") is not True:
            return SmokeResult(
                host_client="codex",
                executable=executable,
                status="failed",
                command=command,
                detail=f"unexpected payload: {raw[:200]}",
            )
        return SmokeResult(
            host_client="codex",
            executable=executable,
            status="passed",
            command=command,
            detail="structured exec returned ok=true",
            output_sample=raw[:200],
        )


def _probe_claude_code(
    executable: str, *, invoke: bool, timeout_seconds: int
) -> SmokeResult:
    help_proc = _run_probe(
        [executable, "--help"],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        stdin="",
        timeout_seconds=30,
    )
    help_text = help_proc.stdout
    for flag in ("--json-schema", "--output-format", "--dangerously-skip-permissions"):
        if flag not in help_text:
            return SmokeResult(
                host_client="claude-code",
                executable=executable,
                status="blocked",
                command=[executable, "--help"],
                detail=f"missing required flag: {flag}",
            )
    if not invoke:
        return SmokeResult(
            host_client="claude-code",
            executable=executable,
            status="probe_only",
            command=[executable, "--help"],
            detail="help verified structured print flags",
        )

    work = REPO_ROOT / ".tmp" / "host-cli-smoke" / "claude"
    work.mkdir(parents=True, exist_ok=True)
    schema_json = json.dumps(MIN_SCHEMA, separators=(",", ":"))
    command = [
        executable,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        schema_json,
        "--dangerously-skip-permissions",
        MIN_PROMPT,
    ]
    env = os.environ.copy()
    env["HARNESS_MEM_AUTONOMOUS_PROVIDER"] = "1"
    proc = _run_probe(
        command,
        cwd=work,
        env=env,
        stdin="",
        timeout_seconds=timeout_seconds,
    )
    if proc.returncode != 0:
        return SmokeResult(
            host_client="claude-code",
            executable=executable,
            status="failed",
            command=command,
            detail=(proc.stderr or proc.stdout or "non-zero exit").strip()[:500],
        )
    stdout = proc.stdout.strip()
    if not stdout:
        return SmokeResult(
            host_client="claude-code",
            executable=executable,
            status="failed",
            command=command,
            detail="empty stdout",
        )
    envelope = json.loads(stdout)
    structured = envelope.get("structured_output")
    if isinstance(structured, dict) and structured.get("ok") is True:
        payload = structured
    else:
        payload = envelope
    if payload.get("ok") is not True:
        return SmokeResult(
            host_client="claude-code",
            executable=executable,
            status="failed",
            command=command,
            detail=f"unexpected payload: {stdout[:200]}",
        )
    return SmokeResult(
        host_client="claude-code",
        executable=executable,
        status="passed",
        command=command,
        detail="print+json-schema returned ok=true",
        output_sample=stdout[:200],
    )


def _probe_hermes(executable: str, *, invoke: bool, timeout_seconds: int) -> SmokeResult:
    help_proc = _run_probe(
        [executable, "chat", "--help"],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        stdin="",
        timeout_seconds=30,
    )
    if help_proc.returncode != 0:
        return SmokeResult(
            host_client="hermes",
            executable=executable,
            status="blocked",
            command=[executable, "chat", "--help"],
            detail=(help_proc.stderr or help_proc.stdout or "chat --help failed").strip(),
        )
    help_text = (help_proc.stdout or "") + (help_proc.stderr or "")
    if "--query-file" not in help_text or "-Q" not in help_text:
        return SmokeResult(
            host_client="hermes",
            executable=executable,
            status="blocked",
            command=[executable, "chat", "--help"],
            detail="missing programmatic chat flags",
        )
    if not invoke:
        return SmokeResult(
            host_client="hermes",
            executable=executable,
            status="probe_only",
            command=[executable, "chat", "--help"],
            detail="help verified hermes chat programmatic flags",
        )
    work = REPO_ROOT / ".tmp" / "host-cli-smoke" / "hermes"
    work.mkdir(parents=True, exist_ok=True)
    schema_json = json.dumps(MIN_SCHEMA, separators=(",", ":"))
    command = [
        executable,
        "chat",
        "-Q",
        "--accept-hooks",
        "--yolo",
        "--query-file",
        "-",
    ]
    env = os.environ.copy()
    env["HARNESS_MEM_AUTONOMOUS_PROVIDER"] = "1"
    proc = _run_probe(
        command,
        cwd=work,
        env=env,
        stdin=f"{MIN_PROMPT}\n\nRespond with JSON only: {schema_json}",
        timeout_seconds=timeout_seconds,
    )
    if proc.returncode != 0:
        return SmokeResult(
            host_client="hermes",
            executable=executable,
            status="failed",
            command=command,
            detail=(proc.stderr or proc.stdout or "non-zero exit").strip()[:500],
        )
    stdout = proc.stdout.strip()
    if not stdout:
        return SmokeResult(
            host_client="hermes",
            executable=executable,
            status="failed",
            command=command,
            detail="empty stdout",
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        start = stdout.find("{")
        end = stdout.rfind("}")
        payload = json.loads(stdout[start : end + 1])
    if payload.get("ok") is not True:
        return SmokeResult(
            host_client="hermes",
            executable=executable,
            status="failed",
            command=command,
            detail=f"unexpected payload: {stdout[:200]}",
        )
    return SmokeResult(
        host_client="hermes",
        executable=executable,
        status="passed",
        command=command,
        detail="hermes chat returned ok=true",
        output_sample=stdout[:200],
    )


def _probe_opencode(executable: str) -> SmokeResult:
    if not executable:
        return SmokeResult(
            host_client="opencode",
            executable="",
            status="blocked",
            command=[],
            detail="opencode executable not found on PATH",
        )
    help_proc = _run_probe(
        [executable, "run", "--help"],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        stdin="",
        timeout_seconds=30,
    )
    if help_proc.returncode != 0:
        help_proc = _run_probe(
            [executable, "--help"],
            cwd=REPO_ROOT,
            env=os.environ.copy(),
            stdin="",
            timeout_seconds=30,
        )
    help_text = (help_proc.stdout or "") + (help_proc.stderr or "")
    if "--output-schema" in help_text:
        status = "probe_only"
        detail = "run --output-schema flag present (invoke not run by default)"
    elif "run" in help_text:
        status = "probe_only"
        detail = "run subcommand present; structured flags need manual verification"
    else:
        status = "blocked"
        detail = "could not verify structured run flags"
    return SmokeResult(
        host_client="opencode",
        executable=executable,
        status=status,
        command=[executable, "run", "--help"],
        detail=detail,
    )


def run_smoke(*, invoke: bool, timeout_seconds: int) -> list[SmokeResult]:
    results: list[SmokeResult] = []
    codex_bin = _resolve_executable("codex")
    if codex_bin:
        results.append(
            _probe_codex(codex_bin, invoke=invoke, timeout_seconds=timeout_seconds)
        )
    else:
        results.append(
            SmokeResult(
                host_client="codex",
                executable="",
                status="blocked",
                command=[],
                detail="codex executable not found on PATH",
            )
        )

    claude_bin = _resolve_executable("claude-code")
    if claude_bin:
        results.append(
            _probe_claude_code(
                claude_bin, invoke=invoke, timeout_seconds=timeout_seconds
            )
        )
    else:
        results.append(
            SmokeResult(
                host_client="claude-code",
                executable="",
                status="blocked",
                command=[],
                detail="claude executable not found on PATH",
            )
        )

    hermes_bin = _resolve_executable("hermes")
    if hermes_bin:
        results.append(
            _probe_hermes(hermes_bin, invoke=invoke, timeout_seconds=timeout_seconds)
        )
    else:
        results.append(
            SmokeResult(
                host_client="hermes",
                executable="",
                status="blocked",
                command=[],
                detail="hermes executable not found on PATH",
            )
        )

    results.append(_probe_opencode(_resolve_executable("opencode")))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--invoke",
        action="store_true",
        help="Run one real structured invocation for codex/claude when supported",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="Timeout for real invocations",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / ".tmp" / "host-cli-smoke-report.json",
        help="Write JSON report to this path",
    )
    args = parser.parse_args()
    results = run_smoke(invoke=args.invoke, timeout_seconds=args.timeout_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "results": [asdict(item) for item in results],
        "summary": {
            item.host_client: item.status for item in results
        },
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for item in results:
        print(
            f"{item.host_client}: {item.status} ({item.detail})",
            flush=True,
        )
    print(f"report: {args.output.resolve()}", flush=True)
    hard_fail = any(
        item.status == "failed"
        for item in results
        if item.host_client in {"codex", "claude-code"}
    )
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
