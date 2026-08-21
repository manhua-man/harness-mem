---
name: "HM: Wake"
description: 通过 MCP `wake` 拉取当前项目的 wake-up 上下文作为新 session 起点
category: Memory
tags: [harness-mem, wake]
wireFormatVersion: hm-wire-v3.5
---

调用 MCP `wake` 工具，把当前项目的 wake-up 上下文拉出来。

**Input**: 可指定项目（`/hm:wake bazi-apps`），省略用 active project。

**Steps**

1. **确认项目**：从 slash 或 active project
2. **调 MCP `wake`**：
   - 默认：`wake(project_name=<project>)`
   - 如果用户明确想看 procedural 提示：`wake(project_name=<project>, include_skill_hints=true)`
3. **恢复只读上下文**：
   - 把 MCP 返回的 wake-up 上下文作为主结果，但不要向用户原样展示
     `# Automatic Memory Maintenance` 私有块
   - 不读取 `distill_maintenance`，不领取 job，不调用 provider，也不写候选或长期知识
   - Hook 创建的会话 job 由已授权 Dream 在后台处理；只有用户明确调用 distill 时，当前宿主才处理会话
   - 如果返回了 skill hints，只把它们当作 hint，不要擅自展开完整 skill body
   - 只有用户继续追问某个 hint 时，才调 `get_skill(skill_id)`
4. **结语**：
   - 有内容：明确告诉用户“以上是 wake-up 上下文，接下来你可以基于这些继续工作”
   - 空结果：提示用户先 `/hm:distill`

**Notes**

- wake context 与 `/hm:wake` 都是只读；它们不构成另一条后台语义执行管线
- `/hm:wake` 的 shipped truth 是一等 MCP `wake` surface，不要退回手工拼 `get_project_profile` / `get_task_handoffs` / `get_confirmed_rules` / `timeline`
- 如果项目从未有过数据，提示用户先 `/hm:distill`
