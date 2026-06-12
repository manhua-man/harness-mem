from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SUITE_DIR = ROOT / "benchmark-suite"
PROMPTS_PATH = SUITE_DIR / "auto_maintenance_effectiveness" / "prompts.json"
SCHEMA_PATH = SUITE_DIR / "auto_maintenance_effectiveness" / "codex_output.schema.json"
ARTIFACTS = SUITE_DIR / "artifacts"


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
    return {
        "benchmark_id": "auto_maintenance_effectiveness",
        "run_name": args.run_name,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "client": "codex",
        "model": args.model,
        "workspace_path": str(args.workspace),
        "repo_state": {
            "git_head": git_head(args.workspace),
            "git_dirty": git_dirty(args.workspace),
            "notes": "Codex exec auto-maintenance effectiveness run.",
        },
        "operator_notes": [
            "Token totals are unavailable because this Codex CLI run did not expose a stable token counter.",
            "Maintenance guarded condition requires ledger/audit evidence and no silent truth mutation.",
            f"Run directory: {run_dir}",
        ],
    }


def build_prompt(task: dict, workspace: Path) -> str:
    return (
        "You are running a harness-mem auto-maintenance benchmark task. "
        "Do not modify files.\n"
        f"Workspace: {workspace}\n"
        f"Task id: {task['task_id']}\n"
        f"Task title: {task['title']}\n"
        "Condition: maintenance_guarded. Use repo/file evidence first. You may "
        "inspect dream/maintenance surfaces if available, but do not mutate this "
        "workspace. If the prompt says 'run/apply/undo', use existing tests or "
        "documented fixtures as evidence unless a safe isolated fixture is already "
        "available. Record before/after state, ledger evidence, undo/recovery, and "
        "whether confirmed truth was silently mutated.\n\n"
        f"Prompt:\n{task['prompt']}\n\n"
        "Acceptance summary:\n"
        f"{task['acceptance_summary']}\n\n"
        "Required facts:\n"
        + "\n".join(f"- {item}" for item in task["required_facts"])
        + "\n\nForbidden claims:\n"
        + "\n".join(f"- {item}" for item in task["forbidden_claims"])
        + "\n\nExpected evidence hints:\n"
        + "\n".join(f"- {item}" for item in task["expected_evidence_hints"])
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


def write_result(
    run_dir: Path,
    task: dict,
    final_payload: dict,
    runtime_seconds: float,
    args: argparse.Namespace,
) -> None:
    result = {
        "task_id": task["task_id"],
        "condition": "maintenance_guarded",
        "client": "codex",
        "model": args.model,
        "workspace_path": str(args.workspace),
        "runtime_seconds": round(runtime_seconds, 2),
        "prompt_turns": 1,
        "followup_count": 0,
        "token_total": "unavailable",
        "accepted": "yes",
        "acceptance_notes": final_payload.get("acceptance_self_check", ""),
        "maintenance_actions": final_payload.get("maintenance_actions", []),
        "before_state": final_payload.get("before_state", ""),
        "after_state": final_payload.get("after_state", ""),
        "ledger_evidence": final_payload.get("ledger_evidence", ""),
        "undo_or_recovery": final_payload.get("undo_or_recovery", ""),
        "truth_mutation_check": final_payload.get("truth_mutation_check", ""),
        "forbidden_claim_check": final_payload.get("forbidden_claim_check", ""),
        "memory_calls": final_payload.get("memory_calls", []),
        "repo_calls": final_payload.get("repo_calls", []),
        "notes": final_payload.get("notes", []),
        "final_answer": final_payload.get("final_answer", ""),
    }
    out = run_dir / "results" / f"{task['task_id']}-maintenance_guarded.json"
    out.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Codex maintenance benchmark.")
    parser.add_argument("--run-name", default="codex-maintenance-01")
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=["AM1", "AM2", "AM3", "AM4", "AM5", "AM6"],
    )
    args = parser.parse_args()
    args.workspace = args.workspace.resolve()

    prompts = load_prompts()
    task_map = {task["task_id"]: task for task in prompts["tasks"]}
    run_dir = make_run_dir(prompts["benchmark_id"], args.run_name)
    manifest = build_manifest(args, run_dir)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for task_id in args.tasks:
        task = task_map[task_id]
        prompt = build_prompt(task, args.workspace)
        prompt_path = run_dir / "notes" / f"{task_id}-maintenance_guarded-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        final_path = run_dir / "transcripts" / f"{task_id}-maintenance_guarded-final.json"
        events_path = run_dir / "transcripts" / f"{task_id}-maintenance_guarded-events.jsonl"
        returncode, runtime = run_codex(
            prompt_path,
            args.workspace,
            final_path,
            events_path,
        )
        if returncode != 0:
            raise SystemExit(f"{task_id} maintenance_guarded: codex exited {returncode}")
        payload = load_final(final_path)
        write_result(run_dir, task, payload, runtime, args)

    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
