"""Read one isolated completion and check the real Codex completion reply."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import patch

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from harness_mem.autonomous.executors.registry import build_semantic_executor  # noqa: E402
from harness_mem.autonomous.worker import autonomous_runtime_fingerprint  # noqa: E402
from harness_mem.config.merge import load_merged_config  # noqa: E402
from harness_mem.mcp import tool_handlers  # noqa: E402
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402


class Reply(BaseModel):
    reply: str


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = json.loads(args.acceptance_report.read_text(encoding="utf-8"))
    if (report.get("status") != "passed" or report.get("provider_name") != "codex_cli"
            or report.get("runtime_fingerprint_current") != autonomous_runtime_fingerprint()):
        raise ValueError("a fresh passing Codex Hook report for this code is required")
    note = Path(report["autonomous"]["note"]["latest_path"]).resolve()
    run = note.parent.parent
    if not run.is_relative_to((REPO_ROOT / ".tmp").resolve()):
        raise ValueError("only repository-local isolated acceptance data may be consumed")
    backend = LocalMemoryBackend(run / "data")
    asyncio.run(backend.init())
    try:
        job = backend.transcript_store.get_distill_job(report["distill_job_id"])
        if job is None:
            raise ValueError("the isolated job is missing")
        with patch.object(tool_handlers, "_backend_provider", lambda: backend), patch(
            "harness_mem.mcp.distill_handlers._session_notes_dir", lambda _: note.parent
        ):
            completion = tool_handlers.tool_finalize_session_distill(job.project_name, job.id, {})
            current = tool_handlers.tool_search_memory(query="", project_name=job.project_name)
        if not completion.get("success") or not completion.get("knowledge_changes"):
            raise ValueError("verified readable completion is missing")
        visible = {key: completion[key] for key in (
            "knowledge_changes", "not_written", "unfinished_work"
        )}
        config = load_merged_config(Path(job.project_root))
        if config.distill_autonomous_cli != "codex":
            raise ValueError("the isolated acceptance project must still explicitly select Codex")
        provider = build_semantic_executor(config, "codex")
        prompt = (
            (REPO_ROOT / "code/plugins/harness-mem/commands/hm/hm.md").read_text(encoding="utf-8")
            + "\n用户请求：整理完成后直接告诉我记住了什么，用中文回复，知识标题和正文请保留原文便于核对。\n"
            + "以下是已完成且搜索回读通过的实际工具结果。不要调用工具、不要修改文件。"
            + "只生成要展示给用户的完成回复，按 schema 返回 reply。\n"
            + json.dumps(visible, ensure_ascii=False)
        )
        result = provider._run(
            {}, runtime_dir=run / "reply-check", heartbeat=None,
            decision_model=Reply, prompt=prompt, temporary_prefix="reply-", error_label="reply",
        )
        reply = result.decision.reply
        checks = {
            "actual_knowledge_visible": all(
                row["title"] in reply and row["statement"] in reply
                for row in visible["knowledge_changes"]
            ),
            "plain_completion_reply": "记住" in reply,
            "no_internal_material": not any(word in reply for word in (
                job.id, job.session_id, "answer_packet", "canonical_truth_ids", "knowledge_changes",
            )),
            "current_view_matches": all(
                {k: row[k] for k in ("module", "title", "statement")} in current["memories"]
                for row in visible["knowledge_changes"]
            ),
            "runtime_unchanged": autonomous_runtime_fingerprint() == report["runtime_fingerprint_current"],
        }
        output = {
            "status": "passed" if all(checks.values()) else "failed",
            "checks": checks, "reply": reply,
            "knowledge_changes": visible["knowledge_changes"],
            "current_knowledge": current["memories"],
            "acceptance_report": str(args.acceptance_report.resolve()),
            "provider": result.receipt(),
            "scope": "One real Codex reply from an isolated verified completion; not all UI paths.",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if output["status"] == "passed" else 1
    finally:
        asyncio.run(backend.close())


if __name__ == "__main__":
    raise SystemExit(main())
