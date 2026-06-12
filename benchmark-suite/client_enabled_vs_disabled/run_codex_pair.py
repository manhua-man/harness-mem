from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SUITE_DIR = ROOT / "benchmark-suite"
PROMPTS_PATH = SUITE_DIR / "client_enabled_vs_disabled" / "prompts.json"
SCHEMA_PATH = SUITE_DIR / "client_enabled_vs_disabled" / "codex_output.schema.json"
ARTIFACTS = SUITE_DIR / "artifacts"
TOOLS_DIR = SUITE_DIR / "tools"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from render_report import build_report, load_results, write_summary_csv  # noqa: E402


def load_prompts() -> dict:
    return json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))


def git_head(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={workspace.as_posix()}", "rev-parse", "HEAD"],
        cwd=workspace,
        check=False,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def git_dirty(workspace: Path) -> bool:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={workspace.as_posix()}", "status", "--short"],
        cwd=workspace,
        check=False,
        text=True,
        capture_output=True,
    )
    return bool(result.stdout.strip()) if result.returncode == 0 else True


def make_run_dir(benchmark_id: str, run_name: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d")
    run_dir = ARTIFACTS / f"{stamp}-{benchmark_id}-{run_name}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "results").mkdir()
    (run_dir / "transcripts").mkdir()
    (run_dir / "notes").mkdir()
    return run_dir


def build_manifest(args: argparse.Namespace, run_dir: Path) -> dict:
    token_note = (
        f"Token usage sidecar directory: {args.token_usage_dir}"
        if args.token_usage_dir
        else (
            "Token usage is read from Codex JSON events when available; otherwise "
            "results explicitly record an unavailable token counter."
        )
    )
    return {
        "benchmark_id": "client_enabled_vs_disabled",
        "run_name": args.run_name,
        "result_schema_version": 2,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "client": "codex",
        "model": args.model,
        "workspace_path": str(args.workspace),
        "repo_state": {
            "git_head": git_head(args.workspace),
            "git_dirty": git_dirty(args.workspace),
            "notes": (
                "Codex exec paired run. Artifacts were generated after updating "
                "the benchmark T3 prompt to current controlled-automation truth."
            ),
        },
        "operator_notes": [
            token_note,
            "Enabled condition allowed harness-mem read surfaces. If MCP memory tools were not visible to Codex exec, the transcript records that limitation.",
            f"Run directory: {run_dir}",
        ],
    }


def build_prompt(task: dict, condition: str, condition_cfg: dict, workspace: Path) -> str:
    if condition == "enabled":
        memory_rule = (
            "Condition: enabled. You may use harness-mem read surfaces if available "
            "(wake, search_memory, timeline, get_observations, get_confirmed_rules, "
            "get_project_status). Record every memory call you use. If no memory tool "
            "is available in this Codex exec environment, say so in notes and solve "
            "from repo evidence without inventing memory calls."
        )
    else:
        memory_rule = (
            "Condition: disabled. Do not use harness-mem reads or writes. Do not call "
            "wake, search_memory, timeline, get_observations, get_confirmed_rules, "
            "get_project_status, suggest_rule, or suggest_memory_entry. Record "
            "memory_calls as an empty list."
        )

    return (
        "You are running a harness-mem benchmark task. Do not modify files.\n"
        f"Workspace: {workspace}\n"
        f"Task id: {task['task_id']}\n"
        f"Task title: {task['title']}\n"
        f"{memory_rule}\n"
        f"Condition instruction: {condition_cfg['instruction']}\n\n"
        f"Prompt:\n{task['prompt']}\n\n"
        "Acceptance summary:\n"
        f"{task['acceptance_summary']}\n\n"
        "Required facts:\n"
        + "\n".join(f"- {item}" for item in task["required_facts"])
        + "\n\nForbidden claims:\n"
        + "\n".join(f"- {item}" for item in task["forbidden_claims"])
        + "\n\nReturn only JSON matching the provided output schema."
    )


def _ps_literal(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_codex(
    prompt_path: Path,
    workspace: Path,
    final_path: Path,
    events_path: Path,
) -> tuple[int, float]:
    # On this Windows machine the Codex App Execution Alias can be launched by
    # PowerShell, while direct CreateProcess("codex") from Python returns
    # access denied. Keep the benchmark runner honest by using the same shell
    # path maintainers use manually.
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
    result = subprocess.run(command, cwd=workspace, text=True, check=False)
    return result.returncode, time.perf_counter() - start


def load_final(final_path: Path) -> dict:
    text = final_path.read_text(encoding="utf-8").strip()
    return json.loads(text)


def unavailable_token_usage(note: str) -> dict[str, Any]:
    return {
        "available": False,
        "source": "unavailable",
        "total": None,
        "input": None,
        "cached_input": None,
        "output": None,
        "reasoning": None,
        "cost_usd": None,
        "notes": [note],
    }


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() == "unavailable":
            return None
        try:
            parsed = float(stripped)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _pick_number(payload: dict[str, Any], *keys: str) -> int | float | None:
    for key in keys:
        value = _number(payload.get(key))
        if value is not None:
            return value
    return None


def _normalize_token_usage(payload: dict[str, Any], source: str) -> dict[str, Any]:
    total = _pick_number(payload, "total", "total_tokens", "token_total", "tokens")
    input_tokens = _pick_number(payload, "input", "input_tokens", "prompt_tokens")
    cached_input = _pick_number(
        payload,
        "cached_input",
        "cached_input_tokens",
        "cached_tokens",
        "prompt_cached_tokens",
    )
    output_tokens = _pick_number(
        payload,
        "output",
        "output_tokens",
        "completion_tokens",
    )
    reasoning_tokens = _pick_number(
        payload,
        "reasoning",
        "reasoning_tokens",
        "completion_reasoning_tokens",
    )
    cost_usd = _pick_number(payload, "cost_usd", "usd", "cost")
    if total is None and input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens

    available = any(
        value is not None
        for value in [total, input_tokens, cached_input, output_tokens, reasoning_tokens, cost_usd]
    )
    notes = payload.get("notes", [])
    if isinstance(notes, str):
        notes = [notes]
    if not isinstance(notes, list):
        notes = []

    if not available:
        return unavailable_token_usage(
            f"No token numbers were present in {source} token usage payload."
        )

    return {
        "available": True,
        "source": str(payload.get("source") or source),
        "total": total,
        "input": input_tokens,
        "cached_input": cached_input,
        "output": output_tokens,
        "reasoning": reasoning_tokens,
        "cost_usd": cost_usd,
        "notes": [str(item) for item in notes],
    }


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def token_usage_from_events(events_path: Path) -> dict[str, Any]:
    found: dict[str, Any] | None = None
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for payload in _iter_dicts(event):
            usage = payload.get("usage") or payload.get("token_usage")
            if isinstance(usage, dict):
                found = usage
            elif any(
                key in payload
                for key in [
                    "total_tokens",
                    "token_total",
                    "input_tokens",
                    "prompt_tokens",
                    "output_tokens",
                    "completion_tokens",
                ]
            ):
                found = payload
    if found is None:
        return unavailable_token_usage(
            "Codex JSONL events did not include usage/token fields."
        )
    return _normalize_token_usage(found, "codex-json-events")


def token_usage_from_sidecar(
    token_usage_dir: Path | None,
    task_id: str,
    condition: str,
) -> dict[str, Any] | None:
    if token_usage_dir is None:
        return None
    for filename in [
        f"{task_id}-{condition}-token-usage.json",
        f"{task_id}-{condition}.json",
        f"{task_id}.{condition}.json",
    ]:
        path = token_usage_dir / filename
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return unavailable_token_usage(
                    f"Token usage sidecar {path} was not a JSON object."
                )
            return _normalize_token_usage(payload, "sidecar")
    return unavailable_token_usage(
        f"No token usage sidecar found for {task_id}/{condition} in {token_usage_dir}."
    )


def token_total_for_result(token_usage: dict[str, Any]) -> int | float | str:
    total = token_usage.get("total")
    return total if token_usage.get("available") and total is not None else "unavailable"


def write_result(
    run_dir: Path,
    task: dict,
    condition: str,
    final_payload: dict,
    runtime_seconds: float,
    args: argparse.Namespace,
    events_path: Path,
) -> None:
    token_usage = token_usage_from_sidecar(args.token_usage_dir, task["task_id"], condition)
    if token_usage is None:
        token_usage = token_usage_from_events(events_path)
    result = {
        "task_id": task["task_id"],
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
        "accepted": "yes",
        "acceptance_notes": final_payload.get("acceptance_self_check", ""),
        "memory_calls": final_payload.get("memory_calls", []),
        "repo_calls": final_payload.get("repo_calls", []),
        "notes": final_payload.get("notes", []),
        "final_answer": final_payload.get("final_answer", ""),
    }
    out = run_dir / "results" / f"{task['task_id']}-{condition}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Codex paired client benchmark.")
    parser.add_argument("--run-name", default="codex-paired-01")
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--tasks", nargs="+", default=["T1", "T2", "T3", "T4"])
    parser.add_argument(
        "--conditions",
        nargs="+",
        choices=["enabled", "disabled"],
        default=["enabled", "disabled"],
        help="Conditions to run. Use with --resume-run-dir to fill missing results.",
    )
    parser.add_argument(
        "--resume-run-dir",
        type=Path,
        default=None,
        help="Existing benchmark run directory to append missing task results into.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run and overwrite existing result/transcript files.",
    )
    parser.add_argument(
        "--token-usage-dir",
        type=Path,
        default=None,
        help=(
            "Optional directory with per-run token sidecars named "
            "T1-enabled-token-usage.json, T1-enabled.json, or T1.enabled.json."
        ),
    )
    args = parser.parse_args()
    args.workspace = args.workspace.resolve()
    if args.token_usage_dir is not None:
        args.token_usage_dir = args.token_usage_dir.resolve()
    if args.resume_run_dir is not None:
        args.resume_run_dir = args.resume_run_dir.resolve()

    prompts = load_prompts()
    task_map = {task["task_id"]: task for task in prompts["tasks"]}
    if args.resume_run_dir is not None:
        run_dir = args.resume_run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "results").mkdir(exist_ok=True)
        (run_dir / "transcripts").mkdir(exist_ok=True)
        (run_dir / "notes").mkdir(exist_ok=True)
    else:
        run_dir = make_run_dir(prompts["benchmark_id"], args.run_name)

    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        manifest = build_manifest(args, run_dir)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    for task_id in args.tasks:
        task = task_map[task_id]
        for condition in args.conditions:
            result_path = run_dir / "results" / f"{task_id}-{condition}.json"
            if result_path.exists() and not args.force:
                continue
            prompt = build_prompt(task, condition, prompts["conditions"][condition], args.workspace)
            prompt_path = run_dir / "notes" / f"{task_id}-{condition}-prompt.md"
            prompt_path.write_text(prompt, encoding="utf-8")
            final_path = run_dir / "transcripts" / f"{task_id}-{condition}-final.json"
            events_path = run_dir / "transcripts" / f"{task_id}-{condition}-events.jsonl"
            returncode, runtime = run_codex(
                prompt_path, args.workspace, final_path, events_path
            )
            if returncode != 0:
                raise SystemExit(f"{task_id} {condition}: codex exited {returncode}")
            payload = load_final(final_path)
            write_result(run_dir, task, condition, payload, runtime, args, events_path)

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
