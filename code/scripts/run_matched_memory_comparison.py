"""Developer-only, isolated collection of real manual memory workflows.

The execution projects receive source text and initial knowledge, never the
oracle. Product semantics and final result wording are not supplied by fixtures.
"""

from __future__ import annotations

import asyncio
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import os
import shutil
import subprocess
import sys
import time
import tomllib
from typing import Any
from uuid import NAMESPACE_URL, uuid5

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from matched_memory_host import validate_external_scope  # noqa: E402

from harness_mem.autonomous.worker import autonomous_runtime_fingerprint  # noqa: E402
from harness_mem.core.schemas import (  # noqa: E402
    AssimilationDecision, KnowledgeCandidate, KnowledgeEntry, ProjectKnowledgeSourceRef,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_source_fingerprint(root: Path) -> str:
    """Freeze all executable/source bytes, including any existing bytecode."""
    rows = [(path.relative_to(root).as_posix(), digest(path))
            for path in sorted(root.rglob("*"))
            if path.is_file() and ".git" not in path.relative_to(root).parts]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


def source_messages(text: str) -> list[tuple[str, str]]:
    """Decode this fixture's explicit role delimiters, not its semantics.

    Source .txt bytes remain intact for full reading. Markdown turn headings
    are structural metadata; an unheaded project preamble stays in the first
    user record rather than being discarded.
    """
    matches = list(re.finditer(r"(?m)^(User|Assistant): ", text))
    if not matches:
        raise ValueError("fixture has no explicit dialogue roles")
    messages = []
    prefix = text[:matches[0].start()].strip()
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end]
        body = re.split(r"\n## Turn \d+ \([^\n]*\)\n", body, maxsplit=1)[0].strip()
        if index == 0 and prefix and not prefix.startswith("# F"):
            body = prefix + "\n" + body
        messages.append((match[1].lower(), body))
    return messages


def native_records(source: dict, project: Path, session_id: str, ordinal: int) -> list[dict]:
    date = datetime(2026, 10, 7, tzinfo=timezone.utc) + timedelta(minutes=ordinal)
    stamp = date.isoformat().replace("+00:00", "Z")
    records = [{"timestamp": stamp, "type": "session_meta", "payload": {
        "id": session_id, "cwd": str(project), "timestamp": stamp, "source": "cli",
        "originator": "fictional-quality-baseline",
    }}]
    turn = 0
    for role, body in source_messages(source["text"]):
        if role == "user" or turn == 0:
            turn += 1
            records.append({"timestamp": stamp, "type": "turn_context", "payload": {
                "turn_id": f"fictional-turn-{turn}", "cwd": str(project),
            }})
        records.append({"timestamp": stamp, "type": "response_item", "payload": {
            "type": "message", "role": role, "phase": "final_answer" if role == "assistant" else None,
            "content": [{"type": "output_text" if role == "assistant" else "input_text", "text": body}],
        }})
    return records


async def seed_isolated_backend(data: Path, project: Path, rows: list[dict]) -> None:
    """Seed equal initial state via existing transaction APIs, not direct SQL."""
    backend = LocalMemoryBackend(data)
    await backend.init()
    try:
        store = backend.structured_store.knowledge_store
        entries = [KnowledgeEntry(project_name=project.name, module_path=["Initial knowledge"],
                                  title=row["title"], statement=row["statement"],
                                  verified_at=datetime.now(timezone.utc)) for row in rows]
        candidate = KnowledgeCandidate(id="fixture-initial-state", project_name=project.name,
                                       candidate_type="memory", statement="Frozen initial state.")
        decision = AssimilationDecision(id="fixture-initial-state", project_name=project.name,
                                        candidate_id=candidate.id, disposition="add",
                                        canonical_truth_ids=[entry.id for entry in entries],
                                        reason="Equal pre-existing fictional state; not an extraction result.")
        await store.save_candidate(candidate)
        source = project / "initial-knowledge.md"
        ref = ProjectKnowledgeSourceRef(label=source.name, target=source.resolve().as_uri(),
                                       kind="repository", digest=digest(source))
        await store.apply_current_change(
            candidate_before=candidate, candidate_after=candidate.model_copy(update={"status": "assimilated"}),
            decision=decision, added_entries=entries, predecessor_entries=[],
            source_refs_by_entry={entry.id: [ref] for entry in entries},
        )
    finally:
        await backend.close()


def prepare_experiment(upstream: Path, run: Path, *, artifact_root: Path | None = None,
                       baseline: dict | None = None) -> dict:
    if artifact_root is None:
        raise ValueError("an explicit external artifact_root is required")
    validate_external_scope(artifact_root, run, upstream, repo=REPO_ROOT)
    artifact_root, run, upstream = artifact_root.resolve(), run.resolve(), upstream.resolve()
    if run.exists():
        raise ValueError("refuse to overwrite an existing experiment")
    if baseline is None:
        raise ValueError("an explicit frozen corpus is required; no historical sample is selected by default")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=upstream, text=True).strip():
        raise ValueError("upstream checkout must be unchanged")
    upstream_fingerprint = upstream_source_fingerprint(upstream)
    run.mkdir(parents=True)
    # Evaluator-only directory, outside both execution working roots.
    write_json(run / "evaluator" / "frozen-baseline.json", baseline)
    arms = {}
    for product in ("harness-mem", "session-distill-skills"):
        arm = run / product
        project = arm / "lantern"
        project.mkdir(parents=True)
        subprocess.run(["git", "init", "--quiet", str(project)], check=True)
        (project / ".harness-mem.toml").write_text("[distill.autonomous]\nenabled = false\n", encoding="utf-8")
        (project / "initial-knowledge.md").write_text("# Initial project knowledge\n\n" + "\n".join(
            f"- **{row['title']}**: {row['statement']}" for row in baseline["initial_knowledge"]
        ) + "\n", encoding="utf-8")
        native = arm / "native-codex"
        native.joinpath("sessions").mkdir(parents=True)
        native.joinpath("archived_sessions").mkdir()
        source_records = []
        for ordinal, source in enumerate(baseline["sources"]):
            session_id = str(uuid5(NAMESPACE_URL, baseline["corpus_sha256"] + ":" + source["id"]))
            path = native / "sessions" / f"rollout-{session_id}.jsonl"
            rows = native_records(source, project, session_id, ordinal)
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            raw = project / "source-text" / f"{session_id}.txt"
            raw.parent.mkdir(exist_ok=True)
            raw.write_text(source["text"], encoding="utf-8", newline="")
            assert digest(raw) == source["sha256"]
            source_records.append({"source_id": source["id"], "session_id": session_id,
                                   "native_path": str(path), "native_sha256": digest(path),
                                   "text_path": str(raw), "text_sha256": digest(raw),
                                   "messages": len(source_messages(source["text"]))})
        manifest = {
            "schema_version": 2, "artifact_root": str(artifact_root),
            "run_root": str(arm), "project_root": str(project),
            "project_name": project.name, "native_root": str(native), "data_dir": str(arm / "data"),
            "notes_dir": str(arm / "notes"), "audit_path": str(arm / "handler-events.jsonl"),
            "upstream_root": str(upstream), "upstream_distill": str(project / "session-distill"),
            "kb_file": str(project / "session-knowledge-base.md"),
            "session_ids": [row["session_id"] for row in source_records],
            "sources": source_records, "corpus_sha256": baseline["corpus_sha256"],
            "runtime_fingerprint": autonomous_runtime_fingerprint(), "upstream_revision": commit,
            "upstream_tree_sha256": upstream_fingerprint,
        }
        (project / "session-knowledge-base.md").write_bytes((project / "initial-knowledge.md").read_bytes())
        write_json(arm / "manifest.json", manifest)
        if product == "harness-mem":
            asyncio.run(seed_isolated_backend(arm / "data", project, baseline["initial_knowledge"]))
        arms[product] = manifest
    return {"schema_version": 1, "corpus_sha256": baseline["corpus_sha256"], "arms": arms}


def safe_configuration() -> dict:
    """Freeze only nonsecret settings; never export endpoint or credentials."""
    path = Path.home() / ".codex" / "config.toml"
    value = tomllib.loads(path.read_text(encoding="utf-8"))
    return {"model": value.get("model"), "model_provider": value.get("model_provider"),
            "model_reasoning_effort": value.get("model_reasoning_effort"),
            "ambient_mcp_names": sorted(value.get("mcp_servers", {})),
            "host": "codex", "background_enabled": False,
            "memories_enabled": False, "web_search": "disabled"}


def install_instructions(product: str, manifest: dict) -> Path:
    project = Path(manifest["project_root"])
    root = project / "product-instructions"
    if product == "harness-mem":
        source = REPO_ROOT / "code/tools/hm-distill"
    else:
        source = Path(manifest["upstream_root"]) / "adapters/codex-session-distill"
    root.mkdir()
    shutil.copy2(source / "SKILL.md", root / "SKILL.md")
    shutil.copytree(source / "references", root / "references")
    if product == "harness-mem":
        shutil.copy2(REPO_ROOT / "code/plugins/harness-mem/commands/hm/hm.md", root / "hm.md")
    (project / "AGENTS.md").write_text(
        "# Isolated fictional project\n\n"
        "Use the supplied product instructions. This project's conversations are fictional.\n"
        "Read only this execution project's supplied sources and initial knowledge.\n"
        "Do not read sibling experiments, evaluator directories, real histories or private memory.\n"
        "Do not change account, model, provider, global configuration or hooks.\n"
        "Do not delegate. Do not remove the original sources.\n"
        "Use the product's existing verification and storage workflow; do not invent a knowledge store.\n",
        encoding="utf-8")
    return root


def command_for(product: str, manifest_path: Path, config: dict, output: Path) -> list[str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    executable = shutil.which("codex.cmd" if os.name == "nt" else "codex")
    if executable is None:
        raise ValueError("configured Codex CLI is unavailable")
    prefix = [executable]
    if os.name == "nt" and Path(executable).suffix.lower() == ".cmd":
        # Invoke the SAME installed npm package without cmd.exe's extra quote pass.
        script = Path(executable).parent / "node_modules/@openai/codex/bin/codex.js"
        node = shutil.which("node.exe")
        if node is None or not script.is_file():
            raise ValueError("cannot safely resolve the installed Codex npm launcher")
        prefix = [node, str(script)]
    command = [*prefix, "exec", "--ephemeral", "--json", "--skip-git-repo-check",
               "-C", manifest["project_root"], "--sandbox", "workspace-write",
               "--add-dir", str(manifest_path.parent), "--output-last-message", str(output)]
    for name in config["ambient_mcp_names"]:
        # The CLI dotted override parser does NOT parse TOML quoted key segments.
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError("MCP name cannot be safely represented in a CLI dotted override")
        command.extend(["-c", f"mcp_servers.{name}.enabled=false"])
    command.extend(["-c", "features.memories=false", "-c", 'web_search="disabled"'])
    if product == "harness-mem":
        wrapper = REPO_ROOT / "code/scripts/matched_memory_host.py"
        for key, value in {"command": sys.executable,
                           "args": ["-B", str(wrapper), "--mode", "hm", "--manifest", str(manifest_path)],
                           "enabled": True,
                           # The operator selected this isolated, path-guarded service.
                           # CLI noninteractive approval_policy=never cannot answer prompts.
                           "default_tools_approval_mode": "approve", "startup_timeout_sec": 60,
                           "tool_timeout_sec": 120}.items():
            command.extend(["-c", f"mcp_servers.matched_hm.{key}={json.dumps(value)}"])
    return [*command, "-"]


def check_cli_configuration(command: list[str]) -> dict:
    """Parse exact overrides without starting a model or any MCP server."""
    prefix = command[:command.index("exec")]
    overrides = []
    for index, item in enumerate(command):
        if item == "-c":
            overrides.extend(["-c", command[index + 1]])
    check = subprocess.run([*prefix, *overrides, "mcp", "list", "--json"],
                           capture_output=True, text=True, encoding="utf-8", timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if check.returncode != 0:
        # Do not export raw mcp-list stdout: it may contain private transport settings.
        return {"status": "failed", "return_code": check.returncode, "model_calls": 0,
                "reason": "CLI rejected temporary configuration"}
    servers = json.loads(check.stdout)
    safe_servers = [{"name": item["name"], "enabled": item["enabled"]} for item in servers]
    expected = {"matched_hm"} if "mcp_servers.matched_hm.enabled=true" in command else set()
    enabled = {item["name"] for item in safe_servers if item["enabled"]}
    return {"status": "passed" if enabled == expected else "failed", "model_calls": 0,
            "servers": safe_servers, "enabled_scope_matches": enabled == expected}


def instruction_files(product: str, manifest: dict) -> list[Path]:
    """Mandatory reading in the execution project, not the evaluator's inputs."""
    project = Path(manifest["project_root"])
    root = project / "product-instructions"
    files = [root / "hm.md"] if product == "harness-mem" else []
    return [*files, root / "SKILL.md", *sorted((root / "references").rglob("*.md")),
            project / "initial-knowledge.md"]


def daily_reply_instructions() -> str:
    """Consume the canonical entry even when the Agent cannot start a terminal."""
    text = (REPO_ROOT / "code/plugins/harness-mem/commands/hm/hm.md").read_text(encoding="utf-8")
    marker = "## 结果与失败"
    if marker not in text:
        raise ValueError("canonical hm reply instructions are missing")
    instructions = text.split(marker, 1)[1].split("\n## ", 1)[0].strip()
    if not instructions:
        raise ValueError("canonical hm reply instructions are missing")
    return marker + "\n\n" + instructions


def workflow_prompt(product: str, manifest_path: Path, *, preflight: bool) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wrapper = REPO_ROOT / "code/scripts/matched_memory_host.py"
    helper = f'& "{sys.executable}" -B "{wrapper}" --mode upstream --manifest "{manifest_path}"'
    files = instruction_files(product, manifest)
    reading = ("先在本次 CLI 的终端逐个完整读取下列说明与初始知识（不是只列文件名、标题或摘要），"
               "确保完整内容出现在成功的终端输出中；输出较长时提高输出上限，不要截断。"
               "任一次读取失败就停止，不自动重试、不换入口、不开始整理。\n"
               + "\n".join(str(path) for path in files) + "\n")
    reply_rules = daily_reply_instructions() + "\n" if product == "harness-mem" else ""
    if manifest.get("device_scope") and product == "harness-mem":
        if preflight:
            return (reply_rules + reading + "This is a read-only device-source availability check. Use only matched_hm. "
                    f"Call inspect_sessions(clients=['codex']) without project_root; verify exactly {len(manifest['session_ids'])} fixed sessions, "
                    "then fully read each through inspect_sessions(action='source') without a directory. "
                    "No prepare/govern/finalize/get_project_status or configuration changes. "
                    "Reply exactly PREFLIGHT_OK only if every mandatory terminal read and complete source read succeeds; otherwise stop and explain in Chinese.")
        return (reply_rules + reading
                + f"整理此隔离设备提供的全部 {len(manifest['session_ids'])} 场虚构会话。范围已明确，不需确认。"
                "使用 matched_hm 唯一隔离 MCP，先 inspect_sessions(clients=['codex'])，不传 project_root。"
                "使用 scope=all、返回的 batch_sessions 固定同一批次，逐场完整读取、提取独立点、核对原话、"
                "与全部当前知识对照、通过 govern_memory 和 finalize_session_distill 实际提交，再普通搜索回读。"
                "后续只传 batch_id 继续。目录缺失或没有目录不是失败；本次不需要任何工程设置。"
                "明确的未来用户偏好用 user_statement 原话和真实 exchange digest 验证；不要凭模型自报verified。"
                "未完成工作单独保留，不当作长期记忆。来源不能删除、后台不能开启。"
                "不得读取真实历史、私有记忆、其他实验、全局配置，不调用网络或其他MCP，不委派。"
                "不使用终端替代记忆写入；终端只读取上述说明。"
                "最后用中文直接展示实际保存内容、没记原因和未完成事项，不只报数量；失败停止不重试。")
    if preflight:
        if product == "harness-mem":
            return (reply_rules + reading + "This is a read-only availability check, not distillation. Call the matched_hm "
                    f"inspect_sessions tool for project_root={manifest['project_root']!r}, clients=['codex']. "
                    f"Verify all {len(manifest['session_ids'])} fixed sessions are readable. Do not create jobs, write knowledge, "
                    "change configuration, or call get_project_status. Reply with exactly PREFLIGHT_OK, with no other text, only if the "
                    "mandatory terminal reads and the actual inventory tool succeeded; otherwise explain failure in ordinary Chinese.")
        return (reading + "This is an isolated preparation check, not semantic distillation. Read the supplied native "
                f"JSONL headers under {manifest['native_root']}. First run {helper} index; then run {helper} bundle "
                f"{manifest['session_ids'][0]}. This native bundle creates isolated preparation material only, "
                "not knowledge. Verify the returned bundle retains full turns for that session. "
                "Do not write knowledge or mark distilled. Reply with exactly PREFLIGHT_OK, with no other text, only on success.")
    common = (
        reply_rules + reading
        + f"整理本项目提供的全部{len(manifest['session_ids'])}场历史会话。范围已明确，不需再次确认。完整读取，逐点验证，"
        "与现有知识对照，留下以后有用的结论，纠正被明确替代的旧说法，不重复写入；"
        "未完成事项单独保留。对用户明确提出的未来偏好或项目决定，用用户原话验证，"
        "不要假设已经有代码实现。不要把临时请求或猜测当事实。\n"
        "必须实际完成本产品自己的验证、写入与收尾流程，并读回最终知识；失败如实停止。"
        "最后用中文展示实际记住的内容、没记的原因和未完成事项，不只给数量或文件链接。\n"
        "不要读取任何 evaluator 目录、另一个产品的输出、真实历史或私有记忆，不调用网络。\n"
        f"先完整阅读 {manifest['project_root']}/product-instructions/SKILL.md 及其相关 references。\n"
        f"初始知识：{manifest['project_root']}/initial-knowledge.md。"
        "它是相同的预先存在状态，不是本次提取答案。\n"
        "供完整阅读的原文和对应的固定会话：\n" + "\n".join(
            f"{row['session_id']} — {row['text_path']}" for row in manifest["sources"]))
    if product == "harness-mem":
        return common + (
            f"\n本项目名={manifest['project_name']}，root={manifest['project_root']}。"
            "当前源代码 MCP matched_hm 已经接好，仅提供隔离数据。不要用其他 MCP 或终端替代记忆写入。"
            "先盘点，然后用已有 prepare/govern/finalize 和同一 batch_id 连续处理全部会话，"
            "prepare 必须指定 client=codex；普通 search_memory 回读，handoff 保存在任务区。"
            "不调用首次安装/get_project_status，不启用后台，不清理来源。")
    return common + (
        "\n上游脚本没有安装到全局；以下开发期包装器只替换来源和输出路径，"
        "调用原有 index/bundle/run/deep/mark 实现，不改变提取、验证或晋升规则。"
        f"\n本次唯一主 KB={manifest['kb_file']}，Note目录={manifest['notes_dir']}，"
        f"workspace={manifest['upstream_distill']}。技能里的 E:/project 和 ~/.codex 路径仅在本实验"
        "映射为上述隔离路径；绝不能访问真实路径或写 Redirect 壳。"
        f"\n脚本入口：{helper} <command>。可用 index，bundle UUID...，run UUID...，"
        "deep --session-ids 全部固定UUID，mark UUID distilled。先 index，再 bundle 全部，再 deep。"
        "生成的 packets/answer-packets 只是待验证材料，必须完成逐Q验证、正式KB晋升、"
        "Session Note终审与 check-work，再原生 mark distilled。默认数量过滤不改变本次明确范围。"
        "若需要补充遗漏的独立问题，按原技能规则完整回看来源，不只处理脚本预提取的标题。"
        "工具自身会在收尾前保留隔离审查副本，原文不得删除；未完成事项留在 Note Open items。")


class UnqualifiedModelDispatch(RuntimeError):
    """The current native transport cannot meet the controlled-test contract."""


def require_qualified_model_dispatch() -> None:
    # A budget JSON flag, a prompt instruction, or a goal's tokenBudget is not a
    # per-provider-call output bound. Do not add a flag that bypasses this check.
    # Replace this refusal only when this executor actually implements verified
    # input/output reservations and controls every native retry before dispatch.
    raise UnqualifiedModelDispatch(
        "Model dispatch disabled: this Codex CLI executor has no qualified full-input "
        "bound, actual output-token limit, retry control, or shared dispatch ledger."
    )


def run_cli(product: str, manifest_path: Path, config: dict, *, preflight: bool,
            timeout_seconds: int) -> dict:
    require_qualified_model_dispatch()
    phase = "preflight" if preflight else "workflow"
    arm = manifest_path.parent
    prefix = arm / phase
    output = prefix.with_suffix(".reply.txt")
    log = prefix.with_suffix(".events.jsonl")
    error = prefix.with_suffix(".stderr.txt")
    prompt = workflow_prompt(product, manifest_path, preflight=preflight)
    prefix.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
    command = command_for(product, manifest_path, config, output)
    static_check = check_cli_configuration(command)
    write_json(prefix.with_suffix(".cli-configuration.json"), static_check)
    if static_check["status"] != "passed":
        result = {"status": "failed", "phase": phase, "model_calls": 0,
                  "reason": "temporary CLI configuration failed before any model invocation",
                  "configuration_check": static_check}
        write_json(prefix.with_suffix(".receipt.json"), result)
        print(json.dumps({"product": product, **result}), flush=True)
        return result
    env = os.environ.copy()
    # Per-invocation Hook recursion guard; no global configuration changes.
    env["HARNESS_MEM_AUTONOMOUS_PROVIDER"] = "1"
    started = time.perf_counter()
    with log.open("wb") as stdout, error.open("wb") as stderr:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                   env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        timed_out = False
        try:
            process.communicate(prompt.encode("utf-8"), timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                # Only the exact process created above, including its CLI shim children.
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                process.kill()
            process.communicate()
    elapsed = time.perf_counter() - started
    events = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    completed = [event for event in events if event.get("type") == "turn.completed"]
    failed = [event for event in events if event.get("type") in {"turn.failed", "error"}]
    usage = completed[-1].get("usage", {}) if completed else {}
    reply = output.read_text(encoding="utf-8") if output.exists() else ""
    okay = process.returncode == 0 and not timed_out and completed and not failed and reply.strip()
    reads_verified = instruction_reads_verified(product, manifest_path, log)
    command_failures = [event["item"] for event in events
                        if event.get("type") == "item.completed"
                        and event.get("item", {}).get("type") == "command_execution"
                        and (event["item"].get("status") == "failed"
                             or event["item"].get("exit_code") != 0)]
    product_failures = failed_mcp_results(events)
    okay = okay and reads_verified and not command_failures and not product_failures
    if preflight:
        okay = okay and preflight_verified(reply, product, manifest_path, events_path=log)
    result = {"status": "passed" if okay else "failed", "phase": phase,
              "return_code": process.returncode, "timed_out": timed_out,
              "instruction_reads_verified": reads_verified,
              "failed_terminal_calls": len(command_failures),
              "failed_product_calls": len(product_failures),
              "product_completion_verified": False,
              "workflow_seconds": elapsed, "usage": usage, "command": command,
              "configuration": config, "events_path": str(log), "reply_path": str(output),
              "events_sha256": digest(log), "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
              "agent_item_count": sum(event.get("type") == "item.completed" for event in events),
              "tool_calls": sum(event.get("type") == "item.completed" and event.get("item", {}).get("type")
                                in {"command_execution", "mcp_tool_call"} for event in events)}
    write_json(prefix.with_suffix(".receipt.json"), result)
    print(json.dumps({"product": product, "phase": phase, "status": result["status"],
                      "seconds": round(elapsed, 3), "usage": usage}), flush=True)
    return result


def failed_mcp_results(events: list[dict]) -> list[dict]:
    """A successful transport or CLI exit cannot turn a rejected write into success."""
    failed = []
    for event in events:
        item = event.get("item", {})
        if event.get("type") != "item.completed" or item.get("type") != "mcp_tool_call":
            continue
        rejected = bool(item.get("error")) or item.get("status") != "completed"
        for content in (item.get("result") or {}).get("content", []):
            if content.get("type") != "text":
                continue
            try:
                value = json.loads(content.get("text", ""))
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict) and value.get("success") is False:
                rejected = True
        if rejected:
            failed.append(item)
    return failed


async def collect_hm(manifest: dict) -> dict:
    backend = LocalMemoryBackend(Path(manifest["data_dir"]))
    await backend.init()
    try:
        store = backend.structured_store.knowledge_store
        entries = await store.list_entries(manifest["project_name"])
        rows = []
        for entry in entries:
            rows.append({"entry": entry.model_dump(mode="json"),
                         "sources": [ref.model_dump(mode="json") for ref in await store.list_sources(entry.id)]})
        handoffs = await backend.structured_store.get_latest_handoffs(manifest["project_name"], limit=None)
        jobs = backend.transcript_store.list_distill_jobs(project_name=manifest["project_name"])
        return {"knowledge": rows, "handoffs": [item.model_dump(mode="json") for item in handoffs],
                "jobs": [item.model_dump(mode="json") for item in jobs]}
    finally:
        await backend.close()


def collect_product(product: str, manifest: dict) -> dict:
    result = {"product": product, "runtime_fingerprint": autonomous_runtime_fingerprint(),
              "oracle_supplied_to_executor": False, "oracle_access_verified": False,
              "oracle_isolation_scope": "Supplied inputs only; terminal reads are not OS-isolated.",
              "human_review": None}
    if product == "harness-mem":
        result.update(asyncio.run(collect_hm(manifest)))
    else:
        kb = Path(manifest["kb_file"])
        result["knowledge_markdown"] = kb.read_text(encoding="utf-8")
        state = Path(manifest["upstream_distill"]) / "manifest.json"
        result["native_manifest"] = json.loads(state.read_text(encoding="utf-8")) if state.exists() else None
    result["notes"] = [{"path": str(path), "sha256": digest(path), "text": path.read_text(encoding="utf-8")}
                       for path in sorted(Path(manifest["notes_dir"]).rglob("*.md"))]
    changed = [row["source_id"] for row in manifest["sources"]
               if digest(Path(row["native_path"])) != row["native_sha256"]
               or digest(Path(row["text_path"])) != row["text_sha256"]]
    result["changed_source_ids"] = changed
    result["source_retention_verified"] = not changed
    return result


def instruction_reads_verified(product: str, manifest_path: Path, events_path: Path) -> bool:
    """Require full contents from successful native terminal output, not Agent prose."""
    if not events_path.is_file():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    references = Path(manifest["project_root"]) / "product-instructions/references"
    if not references.is_dir() or not list(references.rglob("*.md")):
        return False
    outputs = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item", {})
        if (event.get("type") == "item.completed" and item.get("type") == "command_execution"
                and item.get("status") == "completed" and item.get("exit_code") == 0):
            outputs.append(item.get("aggregated_output", "").replace("\r\n", "\n"))
    for path in instruction_files(product, manifest):
        if not path.is_file():
            return False
        text = path.read_text(encoding="utf-8").strip().replace("\r\n", "\n")
        if not text or not any(text in output for output in outputs):
            return False
    return True


def preflight_verified(reply: str, product: str, manifest_path: Path, *, events_path: Path | None = None) -> bool:
    """Exact completion marker PLUS native evidence, never marker substring."""
    if reply.strip() != "PREFLIGHT_OK":
        return False
    events_path = events_path or manifest_path.parent / "preflight.events.jsonl"
    if not instruction_reads_verified(product, manifest_path, events_path):
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("device_scope") and product == "harness-mem":
        audit = Path(manifest["audit_path"])
        if not audit.is_file():
            return False
        calls = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
        observed = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            item = event.get("item", {})
            if (event.get("type") == "item.completed" and item.get("type") == "mcp_tool_call"
                    and item.get("server") == "matched_hm" and item.get("tool") == "inspect_sessions"
                    and item.get("status") == "completed" and not item.get("error")):
                for content in (item.get("result") or {}).get("content", []):
                    if content.get("type") == "text":
                        observed.append(json.loads(content["text"]))
        ready = set()
        discovered = False
        for call in calls:
            params = call.get("params", {})
            arguments = params.get("arguments", {})
            if params.get("name") != "inspect_sessions" or arguments.get("project_root"):
                return False
            for content in call.get("response", {}).get("result", {}).get("content", []):
                if content.get("type") != "text":
                    continue
                value = json.loads(content["text"])
                if value.get("success") is not True or value not in observed:
                    return False
                if arguments.get("action", "inventory") == "inventory":
                    discovered = (value.get("scope") == "all" and
                                  {row.get("session_id") for row in value.get("sessions", [])} == set(manifest["session_ids"]))
                elif arguments.get("action") == "source" and value.get("revision_verified") and value.get("complete"):
                    ready.add(value.get("verified_session", {}).get("session_id"))
        return discovered and ready == set(manifest["session_ids"])
    if product == "harness-mem":
        inventories = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = event.get("item", {})
            if (event.get("type") != "item.completed" or item.get("type") != "mcp_tool_call"
                    or item.get("server") != "matched_hm" or item.get("tool") != "inspect_sessions"
                    or item.get("status") != "completed" or item.get("error")
                    or Path(item.get("arguments", {}).get("project_root", "")).resolve()
                    != Path(manifest["project_root"]).resolve()):
                continue
            for content in (item.get("result") or {}).get("content", []):
                if content.get("type") == "text":
                    try:
                        inventories.append(json.loads(content["text"]))
                    except (json.JSONDecodeError, KeyError):
                        continue
        audit = Path(manifest["audit_path"])
        if not audit.exists():
            return False
        for line in audit.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("params", {}).get("name") != "inspect_sessions":
                continue
            result = row.get("response", {}).get("result", {})
            for content in result.get("content", []):
                if content.get("type") != "text":
                    continue
                inventory = json.loads(content["text"])
                sessions = inventory.get("sessions", [])
                if (inventory in inventories and inventory.get("success") is True
                        and {item.get("session_id") for item in sessions} == set(manifest["session_ids"])
                        and all(item.get("readability") == "readable" for item in sessions)):
                    return True
        return False
    state = Path(manifest["upstream_distill"]) / "manifest.json"
    if not state.exists():
        return False
    sessions = json.loads(state.read_text(encoding="utf-8")).get("sessions", [])
    if {row.get("session_id") for row in sessions} != set(manifest["session_ids"]):
        return False
    first = manifest["sources"][0]
    packet = Path(manifest["upstream_distill"]) / "packets" / f"{first['session_id']}.md"
    if not packet.is_file():
        return False
    text = packet.read_text(encoding="utf-8")
    original = Path(first["text_path"]).read_text(encoding="utf-8")
    return bool(text.strip()) and all(body in text for _, body in source_messages(original))


def assert_frozen_experiment(experiment: dict) -> None:
    """Run BEFORE every native call, not after starting the next product."""
    if (digest(Path(__file__)) != experiment["runner_sha256"]
            or digest(REPO_ROOT / "code/scripts/matched_memory_host.py") != experiment["host_sha256"]):
        raise ValueError("collection script drift; stop before another model call")
    if safe_configuration() != experiment["configuration"]:
        raise ValueError("CLI configuration drift; stop before another model call")
    for path, expected in experiment.get("input_hashes", {}).items():
        if digest(Path(path)) != expected:
            raise ValueError("frozen input drift; stop before another model call")
    for manifest in experiment["arms"].values():
        if upstream_source_fingerprint(Path(manifest["upstream_root"])) != manifest["upstream_tree_sha256"]:
            raise ValueError("upstream source drift; stop before another model call")
        if autonomous_runtime_fingerprint() != manifest["runtime_fingerprint"]:
            raise ValueError("runtime drift; stop before another model call")


def minimum_artifact_gate(product: str, snapshot: dict, manifest: dict) -> bool:
    """Stop another model sample on absent artifacts; NOT semantic acceptance."""
    expected = set(manifest["session_ids"])
    if not snapshot.get("source_retention_verified"):
        return False
    if product == "harness-mem":
        jobs = snapshot.get("jobs", [])
        if {row["session_id"] for row in jobs} != expected or any(row["status"] != "completed" for row in jobs):
            return False
    else:
        state = snapshot.get("native_manifest") or {}
        sessions = state.get("sessions", [])
        if {row["session_id"] for row in sessions} != expected or any(row["status"] != "distilled" for row in sessions):
            return False
    # Job/manifest flags alone are not sufficient, including for this narrow gate.
    notes = snapshot.get("notes", [])
    return all(any(Path(note["path"]).stem == sid and note["text"].strip() for note in notes) for sid in expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--baseline", type=Path, help="Explicit frozen corpus; no implicit old sample")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("timeout-seconds must be positive")
    if not args.prepare_only:
        try:
            require_qualified_model_dispatch()
        except UnqualifiedModelDispatch as exc:
            print(json.dumps({"status": "blocked", "model_calls": 0, "reason": str(exc)}))
            return 2
    if args.artifact_root is None or args.baseline is None:
        parser.error("--prepare-only requires --artifact-root and --baseline")
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    experiment = prepare_experiment(args.upstream, args.run, artifact_root=args.artifact_root,
                                    baseline=baseline)
    config = safe_configuration()
    experiment["configuration"] = config
    for product, manifest in experiment["arms"].items():
        install_instructions(product, manifest)
    experiment["runner_sha256"] = digest(Path(__file__))
    experiment["host_sha256"] = digest(REPO_ROOT / "code/scripts/matched_memory_host.py")
    paths = []
    for product, manifest in experiment["arms"].items():
        project = Path(manifest["project_root"])
        paths.extend(path for path in (project / "product-instructions").rglob("*") if path.is_file())
        paths.extend([args.run / product / "manifest.json", project / "AGENTS.md",
                      project / ".harness-mem.toml", project / "initial-knowledge.md"])
        for source in manifest["sources"]:
            paths.extend([Path(source["native_path"]), Path(source["text_path"])])
    experiment["input_hashes"] = {str(path): digest(path) for path in paths}
    write_json(args.run / "experiment.json", experiment)
    if args.prepare_only:
        print(json.dumps({"status": "prepared", "run": str(args.run.resolve())}))
        return 0
    for product, manifest in experiment["arms"].items():
        path = args.run / product / "manifest.json"
        assert_frozen_experiment(experiment)
        preflight = run_cli(product, path, config, preflight=True, timeout_seconds=min(120, args.timeout_seconds))
        if preflight["status"] != "passed":
            write_json(args.run / "result.json", {"status": "blocked", "failed_product": product,
                                                  "failed_phase": "preflight", "real_quality_comparison": False})
            return 2
        assert_frozen_experiment(experiment)
        workflow = run_cli(product, path, config, preflight=False, timeout_seconds=args.timeout_seconds)
        assert_frozen_experiment(experiment)
        snapshot = collect_product(product, manifest)
        write_json(args.run / product / "persisted-result.json", snapshot)
        if workflow["status"] != "passed" or not minimum_artifact_gate(product, snapshot, manifest):
            write_json(args.run / "result.json", {"status": "partial", "failed_product": product,
                                                  "failed_phase": "workflow", "real_quality_comparison": False})
            return 2
    write_json(args.run / "result.json", {"status": "collected", "real_quality_comparison": False,
        "reason": "Both native executions recorded; persisted completeness and semantic review are still required.",
        "human_review": None, "natural_stop_verified": False, "repeated_performance_verified": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
