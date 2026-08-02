---
name: hm-wake
description: Run the harness-mem wake daily action when the user invokes hm-wake.
---

# hm-wake

This is a user-invocable harness-mem Daily command. Follow the action below through the configured harness-mem MCP server; do not replace it with terminal maintenance commands.

调用 MCP `wake` 工具，把当前项目的 wake-up 上下文拉出来。

**Input**: 可指定项目（`/hm-wake bazi-apps`），省略用 active project。

**Steps**

1. **确认项目**：从 slash 或 active project
2. **调 MCP `wake`**：
   - 默认：`wake(project_name=<project>)`
   - 如果用户明确想看 procedural 提示：`wake(project_name=<project>, include_skill_hints=true)`
3. **恢复上下文并执行 bounded maintenance offer**：
   - 把 MCP 返回的 wake-up 上下文作为主结果，但不要向用户原样展示
     `# Automatic Memory Maintenance` 私有块
   - 检查结构化 `distill_maintenance`；如果
     `agent_execution_required=true`，本次最多处理 `job_ids` 中第一个明确 ID
   - 调 `prepare_session_distill(project_name=<project>,
     distill_job_id=<offered id>, run_ingest=false, evidence_mode="semantic",
     detail_level="compact", budget_tokens=3000)`，按返回的 semantic window / raw
     proof 指引完成审查，只为确有价值的内容写 candidate，然后调
     `finalize_session_distill`
   - 如果该 job 失败，调
     `prepare_session_distill(defer_job_id=<offered id>, defer_reason=<bounded reason>,
     run_ingest=false)`，不要阻塞用户当前任务，也不要在同一 task 继续领取新 job
   - 没有 offer 时保持纯 wake；不要要求用户为了 parked backlog 另外运行 `/hm-distill`
   - 如果返回了 skill hints，只把它们当作 hint，不要擅自展开完整 skill body
   - 只有用户继续追问某个 hint 时，才调 `get_skill(skill_id)`
4. **结语**：
   - 有内容：明确告诉用户“以上是 wake-up 上下文，接下来你可以基于这些继续工作”
   - 空结果：提示用户先 `/hm-distill`

**Notes**

- wake context 本身只读；runtime 可以记录一个 bounded Agent maintenance offer，
  只有当前 Agent 的 prepare / finalize 调用才执行语义处理
- `/hm-wake` 的 shipped truth 是一等 MCP `wake` surface，不要退回手工拼 `get_project_profile` / `get_task_handoffs` / `get_confirmed_rules` / `timeline`
- 如果项目从未有过数据，提示用户先 `/hm-distill`
