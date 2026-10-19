"""No-model, isolated MCP reading probe using frozen upstream code and fixtures.

Only pre-existing active facts are seeded. This does not exercise extraction,
automatic recording, correction, answering, or the official benchmark suite.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from uuid import NAMESPACE_URL, uuid5

sys.dont_write_bytecode = True
SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))

from matched_memory_host import Manifest, validate_external_scope  # noqa: E402
from run_matched_memory_comparison import (  # noqa: E402
    digest, native_records, seed_isolated_backend, write_json,
)

EXPECTED_PRECISION_COMMIT = "b95d6abb471c0d591c440172283dd74e7af000df"
MAX_ARTIFACT_BYTES = 200_000_000


def artifact_bytes(root: Path) -> int:
    total = 0
    # Negative scope tests may retain symlink/junction fixtures. Account for the
    # directory entry itself, never traverse or count their external targets.
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(folder) / name
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                total += path.lstat().st_size
                dirs.remove(name)
        for name in files:
            total += (Path(folder) / name).lstat().st_size
    if total > MAX_ARTIFACT_BYTES:
        raise ValueError("task artifact limit exceeded")
    return total


def upstream_bridge(root: Path, mode: str, recorded: Path | None = None) -> dict:
    args = ["node", "--disable-warning=ExperimentalWarning",
            str(SCRIPT_ROOT / "precision_memory_bridge.mjs"), mode, str(root)]
    if recorded is not None:
        args.append(str(recorded))
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
    return json.loads(result.stdout)


def probe_source_hashes() -> dict[str, str]:
    repo = SCRIPT_ROOT.parent.parent
    sources = list((repo / "harness_mem").rglob("*.py")) + [
        SCRIPT_ROOT / name for name in (
            "qualify_memory_comparison.py", "precision_memory_bridge.mjs",
            "matched_memory_host.py", "run_matched_memory_comparison.py",
        )
    ]
    return {str(path.relative_to(repo)).replace("\\", "/"): digest(path)
            for path in sorted(sources)}


def run_probe(artifact_root: Path, upstream: Path, *, run_name: str = "read-probe") -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", run_name):
        raise ValueError("probe name must be one simple directory name")
    run = artifact_root / run_name
    validate_external_scope(artifact_root, run, upstream)
    if run.exists():
        raise ValueError("refuse to overwrite a previous probe")
    artifact_bytes(artifact_root)
    source_hashes = probe_source_hashes()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=upstream, text=True).strip()
    if commit != EXPECTED_PRECISION_COMMIT or dirty:
        raise ValueError("upstream version is not the frozen clean PrecisionMemBench mirror")
    prepared = upstream_bridge(upstream, "prepare")
    if not prepared["cases"] or not prepared["beliefs"]:
        raise ValueError("no applicable upstream material")
    project = run / "project"
    project.mkdir(parents=True)
    (project / ".harness-mem.toml").write_text("[distill.autonomous]\nenabled = false\n", encoding="utf-8")
    initial = project / "initial-knowledge.md"
    initial.write_text(json.dumps(prepared["beliefs"], ensure_ascii=False), encoding="utf-8")
    asyncio.run(seed_isolated_backend(run / "data", project, prepared["beliefs"]))
    sid = str(uuid5(NAMESPACE_URL, "harness-mem-no-model-pmb-read-probe-20261017"))
    native = run / "native-codex"
    (native / "sessions").mkdir(parents=True)
    (native / "archived_sessions").mkdir()
    source = {"text": "User: Use only these fictional pre-existing facts for an isolated read probe.\n"}
    write_json(run / "adapter-input.json", prepared)
    records = native_records(source, project, sid, 0)
    (native / "sessions" / f"rollout-{sid}.jsonl").write_text(
        "\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    manifest = {"schema_version": 2, "artifact_root": str(artifact_root), "run_root": str(run),
        "project_root": str(project), "project_name": "project", "native_root": str(native),
        "data_dir": str(run / "data"), "notes_dir": str(run / "notes"),
        "audit_path": str(run / "calls.jsonl"), "upstream_root": str(upstream),
        "upstream_distill": str(run / "unused-upstream"), "kb_file": str(run / "unused-kb.md"),
        "session_ids": [sid]}
    manifest_path = run / "manifest.json"
    write_json(manifest_path, manifest)
    Manifest(manifest_path)  # Actual external path/config/native validation before launch.
    lookup = {(row["title"], row["statement"]): row["id"] for row in prepared["beliefs"]}
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", HARNESS_MEM_DATA_DIR=str(run / "data"),
               HARNESS_MEM_AUTONOMOUS_PROVIDER="1")
    channel: queue.Queue = queue.Queue()
    observations = []
    cold_start = time.perf_counter()
    with (run / "stderr.txt").open("w", encoding="utf-8") as error:
        process = subprocess.Popen([sys.executable, "-B", str(SCRIPT_ROOT / "matched_memory_host.py"),
            "--mode", "hm", "--manifest", str(manifest_path), "--_child"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error,
            text=True, encoding="utf-8", env=env, cwd=project)

        def pump() -> None:
            for line in process.stdout:
                channel.put(line)
            channel.put(None)

        threading.Thread(target=pump, daemon=True).start()
        try:
            for index in range(31):
                case = prepared["cases"][max(0, index - 1) % len(prepared["cases"])]
                started = cold_start if index == 0 else time.perf_counter()
                request = {"jsonrpc": "2.0", "id": index + 1, "method": "tools/call",
                    "params": {"name": "search_memory", "arguments": {
                        "query": case["query"], "scope": "project", "project_name": "project",
                        "budget_tokens": 20000}}}
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
                line = channel.get(timeout=30)
                if line is None:
                    raise RuntimeError("isolated MCP exited before readback; see stderr.txt")
                response = json.loads(line)
                elapsed = (time.perf_counter() - started) * 1000
                if response.get("id") != index + 1 or "error" in response:
                    raise RuntimeError("isolated MCP rejected request; see recorded calls")
                result = response["result"]
                payload = json.loads(result["content"][0]["text"])
                if result.get("isError") or payload.get("status") not in ("answered", "empty"):
                    raise RuntimeError("isolated memory read failed")
                if payload.get("continuation") or payload.get("next_cursor"):
                    raise RuntimeError("incomplete response cannot be scored")
                memories = payload.get("memories", [])
                ids = []
                for row in memories:
                    identity = (row["title"], row["statement"])
                    if identity not in lookup:
                        raise RuntimeError("read returned content outside the frozen fixture")
                    ids.append(lookup[identity])
                observation = {"caseId": case["caseId"], "cold": index == 0,
                               "latencyMs": elapsed, "ids": ids, "response": payload}
                observations.append(observation)
                write_json(run / "observations.json", observations)
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            process.stdout.close()
    scored = upstream_bridge(upstream, "score", run / "observations.json")
    if scored.get("benchmarkQualification") != prepared.get("benchmarkQualification"):
        raise ValueError("benchmark capability assessment changed during probe")
    write_json(run / "upstream-scoring.json", scored)
    if upstream_bridge(upstream, "prepare")["provenance"] != prepared["provenance"]:
        raise ValueError("upstream source bytes changed during probe")
    if probe_source_hashes() != source_hashes:
        raise ValueError("runtime or adapter source bytes changed during probe")
    warm = sorted(row["latencyMs"] for row in observations if not row["cold"])
    report = {"status": "completed_read_probe_only", "model_provider_requests": 0,
        "model_tokens": 0, "model_execution_seconds": 0, "upstream_commit": commit,
        "warm_requests": len(warm), "cold_start_and_first_read_ms": observations[0]["latencyMs"],
        "warm_p50_ms": warm[14], "warm_p95_ms": warm[28], "warm_max_ms": warm[-1],
        "distinct_upstream_cases_read": len({row["caseId"] for row in observations}),
        "upstream_scoring": scored["summary"], "unsupported_cases": scored["unsupported"],
        "benchmark_qualification": prepared["benchmarkQualification"],
        "provenance": prepared["provenance"], "fixture_sha256": digest(initial),
        "source_hashes": source_hashes,
        "claim_scope": "Unqualified raw assertion replay over preseeded facts and isolated MCP reads; no comparative quality, capture, correction, answer or official benchmark pass",
        "artifact_bytes_before_report": artifact_bytes(artifact_root)}
    write_json(run / "report.json", report)
    artifact_bytes(artifact_root)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--precision-root", type=Path, required=True)
    parser.add_argument("--run-name", default="read-probe")
    args = parser.parse_args()
    report = run_probe(args.artifact_root, args.precision_root, run_name=args.run_name)
    print(json.dumps({key: report[key] for key in (
        "status", "model_provider_requests", "warm_requests", "cold_start_and_first_read_ms",
        "warm_p50_ms", "warm_p95_ms", "warm_max_ms", "artifact_bytes_before_report")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
