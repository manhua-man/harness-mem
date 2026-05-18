---
name: "HM: Wake"
description: 拉取项目过往上下文（最近 handoff、已确认规则、profile）作为新 session 起点
category: Memory
tags: [harness-mem, wake]
---

把当前项目的 wake-up 上下文拉出来：profile、最近任务交接、已确认规则、最近观察。

**Input**: 可指定项目（`/hm:wake bazi-apps`），省略用 active project。

**Steps**

1. **确认项目**：从 slash 或 active project
2. **并行调 MCP 工具**（充分利用工具）：
   - `get_project_profile(project_name=<project>)` — 项目档案
   - `get_task_handoffs(project_name=<project>, limit=5)` — 最近 5 条任务交接
   - `get_confirmed_rules(project_name=<project>)` — 已生效规则
   - `timeline(project_name=<project>, limit=10)` — 最近 10 条 observation
3. **整合呈现**：
   - 项目档案（描述、技术栈、关键文件、约定）
   - 已生效规则（pattern → trigger）
   - 最近的任务交接（哪个 task 卡在哪、下一步是什么、阻塞）
   - 最近的事件时间线
4. **结语**：明确告诉用户"以上是 wake-up 上下文，接下来你可以基于这些继续工作"

**Notes**

- 这是只读操作
- 如果项目从未有过数据（profile/handoffs/rules 都空），提示用户先 `/hm:distill`
