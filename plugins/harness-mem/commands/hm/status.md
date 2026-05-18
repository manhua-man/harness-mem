---
name: "HM: Status"
description: 通过 MCP 查看当前项目的健康度和下一步建议
category: Memory
tags: [harness-mem, status]
---

通过 MCP 显示当前项目的记忆状态，并给出下一步建议。

**Input**: 可指定项目（`/hm:status bazi-apps`），省略则用 active project。

**Steps**

1. 调 MCP `get_project_status`（带项目参数如果有；省略时读取 active project）
2. 并行补充：
   - `get_project_profile(project_name=<project>)`
   - `list_candidates(project_name=<project>, status="pending", limit=20)`
   - `timeline(project_name=<project>, limit=5)`
3. 解析结果，重点关注：
   - Observations / Memory entries / Confirmed rules 数量
   - Pending candidates 数量
   - 最近 observations 是否存在
4. 用自然语言总结给用户，并给出具体可点的 slash 建议：
   - 如果无 observations → 建议用户跑 `/hm:distill`
   - 如果有 pending 候选 → 说明 `/hm:distill` 会自动处理低风险候选；`/hm:review` 仅用于复查/纠错
   - 如果已有上下文 → 建议 `/hm:wake`

**Notes**

- 不修改任何状态，只读
- 不要求用户手动运行 CLI；CLI 只作为开发者排障兜底
