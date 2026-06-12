from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SUITE_DIR = ROOT / "benchmark-suite"
BENCHMARK_ID = "memory_shortcut_vs_source_recovery"
PROMPTS_PATH = SUITE_DIR / BENCHMARK_ID / "prompts.json"
SCHEMA_PATH = SUITE_DIR / BENCHMARK_ID / "codex_output.schema.json"
PACKETS_PATH = SUITE_DIR / BENCHMARK_ID / "shortcut_packets.json"
ARTIFACTS = SUITE_DIR / "artifacts"
TOOLS_DIR = SUITE_DIR / "tools"

CLIENT_RUNNER_DIR = SUITE_DIR / "client_enabled_vs_disabled"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from render_report import build_report, load_results, write_summary_csv  # noqa: E402


def _load_client_runner_helpers() -> Any:
    path = CLIENT_RUNNER_DIR / "run_codex_pair.py"
    spec = importlib.util.spec_from_file_location("client_enabled_runner_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load client runner helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CLIENT_RUNNER = _load_client_runner_helpers()
_ps_literal = _CLIENT_RUNNER._ps_literal
git_dirty = _CLIENT_RUNNER.git_dirty
git_head = _CLIENT_RUNNER.git_head
token_total_for_result = _CLIENT_RUNNER.token_total_for_result
token_usage_from_events = _CLIENT_RUNNER.token_usage_from_events
token_usage_from_sidecar = _CLIENT_RUNNER.token_usage_from_sidecar


def load_prompts() -> dict[str, Any]:
    return json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))


def load_packets() -> dict[str, Any]:
    return json.loads(PACKETS_PATH.read_text(encoding="utf-8"))


def make_run_dir(run_name: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d")
    run_dir = ARTIFACTS / f"{stamp}-{BENCHMARK_ID}-{run_name}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "results").mkdir()
    (run_dir / "transcripts").mkdir()
    (run_dir / "notes").mkdir()
    return run_dir


def build_manifest(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    token_note = (
        f"Token usage sidecar directory: {args.token_usage_dir}"
        if args.token_usage_dir
        else (
            "Token usage is read from Codex JSON events when available; otherwise "
            "results explicitly record an unavailable token counter."
        )
    )
    return {
        "benchmark_id": BENCHMARK_ID,
        "run_name": args.run_name,
        "artifact_state": "accepted" if args.release_snapshot else "diagnostic",
        "accepted": None if not args.release_snapshot else None,
        "release_snapshot": bool(args.release_snapshot),
        "result_schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "client": "codex",
        "model": args.model,
        "workspace_path": str(args.workspace),
        "claim_gate": load_prompts().get("claim_gate", {}),
        "repo_state": {
            "git_head": git_head(args.workspace),
            "git_dirty": git_dirty(args.workspace),
            "notes": (
                "Codex exec paired run for long-source memory shortcut signal. "
                "Raw artifacts are local benchmark outputs."
            ),
        },
        "operator_notes": [
            token_note,
            "Enabled condition must use memory first when the surface is available, then verify against source.",
            "Disabled condition forbids harness-mem read/write surfaces.",
            f"Run directory: {run_dir}",
        ],
    }


def build_prompt(
    task: dict[str, Any],
    condition: str,
    condition_cfg: dict[str, Any],
    workspace: Path,
    packet: dict[str, Any] | None,
) -> str:
    packet_text = ""
    task_type = str(task.get("task_type", ""))
    if condition == "enabled":
        if task_type == "negative_control":
            budget_instruction = task.get(
                "budget_instruction",
                (
                    "Hard budget: use current local evidence only, with at most one "
                    "source file and at most three repo/tool calls."
                ),
            )
            memory_rule = (
                "Condition: enabled negative control. Do not use harness-mem memory "
                "surfaces unless the current local file evidence is unavailable. "
                "This task is designed to show little or no memory advantage. "
                "Record memory_calls as an empty list when local evidence is enough. "
                f"{budget_instruction}"
            )
        elif packet:
            memory_rule = (
                "Condition: enabled. Use the provided accepted memory shortcut packet "
                "below before reading source files. Treat it as a memory read artifact, "
                "not as authority. Record memory_calls with "
                f"'provided_memory_packet:{packet['packet_id']}'. Then verify with the "
                "smallest necessary source reads. Source verification target: read one "
                "source file or artifact. Hard budget: read at most two source files or "
                "artifacts unless the first two contradict the packet or lack the "
                "required evidence. Prefer targeted search snippets over full-file reads. "
                "Do not inspect every source pointer just to be exhaustive. If you exceed "
                "the budget, record the reason in notes."
            )
            packet_text = (
                "\n\nAccepted memory shortcut packet:\n"
                f"packet_id: {packet['packet_id']}\n"
                f"summary: {packet['summary']}\n"
                "facts:\n"
                + "\n".join(f"- {item}" for item in packet.get("facts", []))
                + "\nsource_pointers:\n"
                + "\n".join(f"- {item}" for item in packet.get("source_pointers", []))
            )
        else:
            memory_rule = (
                "Condition: enabled. No precomputed packet was provided. Use harness-mem "
                "read surfaces first if available (wake, search_memory, timeline, "
                "get_observations, get_confirmed_rules, get_project_status). Then verify "
                "with the smallest necessary source reads."
            )
    else:
        budget_instruction = ""
        if task_type == "negative_control":
            budget_instruction = " " + task.get(
                "budget_instruction",
                (
                    "Hard budget: use current local evidence only, with at most one "
                    "source file and at most three repo/tool calls."
                ),
            )
        memory_rule = (
            "Condition: disabled. Do not use harness-mem reads or writes. Do not call "
            "wake, search_memory, timeline, get_observations, get_confirmed_rules, "
            "get_project_status, suggest_rule, or suggest_memory_entry. Record "
            "memory_calls as an empty list. Recover the facts from source material; "
            "read enough source files or artifacts to establish the answer without "
            f"using the shortcut packet.{budget_instruction}"
        )

    expected_sources = task.get("expected_source_classes", [])
    return (
        "You are running a harness-mem memory-shortcut benchmark task. Do not modify files.\n"
        f"Workspace: {workspace}\n"
        f"Task id: {task['task_id']}\n"
        f"Task title: {task['title']}\n"
        f"Task type: {task_type}\n"
        f"{memory_rule}\n"
        f"Condition instruction: {condition_cfg['instruction']}\n\n"
        f"{packet_text}\n\n"
        f"Prompt:\n{task['prompt']}\n\n"
        "Acceptance summary:\n"
        f"{task['acceptance_summary']}\n\n"
        "Required facts:\n"
        + "\n".join(f"- {item}" for item in task["required_facts"])
        + "\n\nForbidden claims:\n"
        + "\n".join(f"- {item}" for item in task["forbidden_claims"])
        + "\n\nExpected source classes:\n"
        + "\n".join(f"- {item}" for item in expected_sources)
        + "\n\nExpected source classes are allowed evidence targets, not a checklist "
        "requiring every listed source to be inspected. Prefer the smallest targeted "
        "source span that verifies the required facts.\n\n"
        "Return only JSON matching the provided output schema. "
        "Set source_read_count to the number of distinct source files or artifacts you inspected. "
        "Set cited_sources to the source paths or artifact names you used."
    )


def run_codex(
    prompt_path: Path,
    workspace: Path,
    final_path: Path,
    events_path: Path,
    *,
    timeout_seconds: int | None,
) -> tuple[int, float]:
    script = (
        "$ErrorActionPreference = 'Continue'; "
        f"$prompt = Get-Content -LiteralPath {_ps_literal(prompt_path)} -Raw; "
        "$prompt | "
        f"& codex -a never exec --cd {_ps_literal(workspace)} --sandbox read-only "
        f"--json --output-schema {_ps_literal(SCHEMA_PATH)} "
        f"--output-last-message {_ps_literal(final_path)} - "
        f"2>&1 | Set-Content -LiteralPath {_ps_literal(events_path)} -Encoding UTF8"
    )
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]
    start = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        runtime = time.perf_counter() - start
        timeout_note = (
            f"\nrun_codex timeout after {timeout_seconds}s for prompt {prompt_path.name}\n"
        )
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(timeout_note)
        return 124, runtime
    return result.returncode, time.perf_counter() - start


def should_retry(events_path: Path) -> bool:
    if not events_path.exists():
        return True
    text = events_path.read_text(encoding="utf-8", errors="replace")
    return "429 Too Many Requests" in text or "exceeded retry limit" in text


def run_codex_with_retries(
    prompt_path: Path,
    workspace: Path,
    final_path: Path,
    events_path: Path,
    *,
    max_attempts: int,
    retry_delay_seconds: int,
    per_call_timeout_seconds: int | None,
) -> tuple[int, float]:
    total_runtime = 0.0
    returncode = 1
    for attempt in range(1, max_attempts + 1):
        returncode, runtime = run_codex(
            prompt_path,
            workspace,
            final_path,
            events_path,
            timeout_seconds=per_call_timeout_seconds,
        )
        total_runtime += runtime
        if returncode == 0:
            return returncode, total_runtime
        if attempt >= max_attempts or not should_retry(events_path):
            return returncode, total_runtime
        time.sleep(retry_delay_seconds)
    return returncode, total_runtime


def load_final(final_path: Path) -> dict[str, Any]:
    text = final_path.read_text(encoding="utf-8").strip()
    return json.loads(text)


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value:
        return [value]
    return []


def _as_non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    if isinstance(value, str):
        try:
            return max(int(float(value.strip())), 0)
        except ValueError:
            return 0
    return 0


def write_result(
    run_dir: Path,
    task: dict[str, Any],
    condition: str,
    final_payload: dict[str, Any],
    runtime_seconds: float,
    args: argparse.Namespace,
    events_path: Path,
) -> None:
    token_usage = token_usage_from_sidecar(args.token_usage_dir, task["task_id"], condition)
    if token_usage is None:
        token_usage = token_usage_from_events(events_path)
    source_read_count = _as_non_negative_int(final_payload.get("source_read_count"))
    cited_sources = _as_string_list(final_payload.get("cited_sources"))
    result = {
        "task_id": task["task_id"],
        "task_type": task.get("task_type", ""),
        "condition": condition,
        "client": "codex",
        "model": args.model,
        "workspace_path": str(args.workspace),
        "runtime_seconds": round(runtime_seconds, 2),
        "prompt_turns": 1,
        "followup_count": 0,
        "token_total": token_total_for_result(token_usage),
        "token_input": token_usage.get("input"),
        "token_cached_input": token_usage.get("cached_input"),
        "token_output": token_usage.get("output"),
        "token_reasoning": token_usage.get("reasoning"),
        "token_cost_usd": token_usage.get("cost_usd"),
        "token_source": token_usage.get("source"),
        "token_counter_available": bool(token_usage.get("available")),
        "token_usage": token_usage,
        "source_read_count": source_read_count,
        "cited_sources": cited_sources,
        "accepted": "yes",
        "acceptance_notes": final_payload.get("acceptance_self_check", ""),
        "memory_calls": _as_string_list(final_payload.get("memory_calls")),
        "repo_calls": _as_string_list(final_payload.get("repo_calls")),
        "notes": _as_string_list(final_payload.get("notes")),
        "final_answer": final_payload.get("final_answer", ""),
    }
    out = run_dir / "results" / f"{task['task_id']}-{condition}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Codex memory-shortcut paired benchmark.")
    parser.add_argument("--run-name", default="codex-memory-shortcut-01")
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--tasks", nargs="+", default=["MS1", "NC2"])
    parser.add_argument(
        "--conditions",
        nargs="+",
        choices=["enabled", "disabled"],
        default=["enabled", "disabled"],
    )
    parser.add_argument("--resume-run-dir", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--token-usage-dir", type=Path, default=None)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=int, default=30)
    parser.add_argument(
        "--per-call-timeout-seconds",
        type=int,
        default=1800,
        help="Abort one Codex condition run after this many seconds; use 0 to disable.",
    )
    parser.add_argument(
        "--release-snapshot",
        action="store_true",
        help="Opt this run into release-snapshot consideration after review.",
    )
    args = parser.parse_args()
    args.workspace = args.workspace.resolve()
    if args.token_usage_dir is not None:
        args.token_usage_dir = args.token_usage_dir.resolve()
    if args.resume_run_dir is not None:
        args.resume_run_dir = args.resume_run_dir.resolve()
    if args.per_call_timeout_seconds <= 0:
        args.per_call_timeout_seconds = None

    prompts = load_prompts()
    packets = load_packets()
    task_map = {task["task_id"]: task for task in prompts["tasks"]}
    if args.resume_run_dir is not None:
        run_dir = args.resume_run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "results").mkdir(exist_ok=True)
        (run_dir / "transcripts").mkdir(exist_ok=True)
        (run_dir / "notes").mkdir(exist_ok=True)
    else:
        run_dir = make_run_dir(args.run_name)

    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        manifest_path.write_text(
            json.dumps(build_manifest(args, run_dir), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (run_dir / "notes" / "shortcut_packets.json").write_text(
            json.dumps(packets, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    for task_id in args.tasks:
        task = task_map[task_id]
        for condition in args.conditions:
            result_path = run_dir / "results" / f"{task_id}-{condition}.json"
            if result_path.exists() and not args.force:
                continue
            prompt = build_prompt(
                task,
                condition,
                prompts["conditions"][condition],
                args.workspace,
                packets.get(task_id) if condition == "enabled" else None,
            )
            prompt_path = run_dir / "notes" / f"{task_id}-{condition}-prompt.md"
            prompt_path.write_text(prompt, encoding="utf-8")
            final_path = run_dir / "transcripts" / f"{task_id}-{condition}-final.json"
            events_path = run_dir / "transcripts" / f"{task_id}-{condition}-events.jsonl"
            returncode, runtime = run_codex_with_retries(
                prompt_path,
                args.workspace,
                final_path,
                events_path,
                max_attempts=args.max_attempts,
                retry_delay_seconds=args.retry_delay_seconds,
                per_call_timeout_seconds=args.per_call_timeout_seconds,
            )
            if returncode != 0:
                raise SystemExit(f"{task_id} {condition}: codex exited {returncode}")
            payload = load_final(final_path)
            write_result(run_dir, task, condition, payload, runtime, args, events_path)

    (run_dir / "notes" / "method.md").write_text(
        (
            "Memory-shortcut smoke run. Positive token/cost claims require the "
            "full threshold in memory_shortcut_vs_source_recovery/prompts.json.\n"
        ),
        encoding="utf-8",
    )
    rows = load_results(run_dir / "results")
    write_summary_csv(run_dir, rows, prompts["benchmark_id"])
    (run_dir / "report.md").write_text(
        build_report(rows, prompts["benchmark_id"]),
        encoding="utf-8",
    )
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
