---
name: hm-wake
description: Run the harness-mem wake daily action when the user invokes hm-wake.
---

# hm-wake

This is a user-invocable harness-mem Daily command. Follow the action below through the configured harness-mem MCP server; do not replace it with terminal maintenance commands.

调用 MCP `wake` 工具，把当前项目的 wake-up 上下文拉出来。

**Input**: 可指定项目（`$hm-wake bazi-apps`），省略用 active project。

**Steps**

1. **确认项目**：从 slash 或 active project
2. **调 MCP `wake`**：
   - 默认：`wake(project_name=<project>)`
   - 如果用户明确想看 procedural 提示：`wake(project_name=<project>, include_skill_hints=true)`
3. **直接呈现 `wake.output`**：
   - 把 MCP 返回的 wake-up 文本作为主结果
   - 如果返回了 skill hints，只把它们当作 hint，不要擅自展开完整 skill body
   - 只有用户继续追问某个 hint 时，才调 `get_skill(skill_id)`
4. **结语**：
   - 有内容：明确告诉用户“以上是 wake-up 上下文，接下来你可以基于这些继续工作”
   - 空结果：提示用户先 `$hm-distill`

**Notes**

- 这是只读操作
- `$hm-wake` 的 shipped truth 是一等 MCP `wake` surface，不要退回手工拼 `get_project_profile` / `get_task_handoffs` / `get_confirmed_rules` / `timeline`
- 如果项目从未有过数据，提示用户先 `$hm-distill`
