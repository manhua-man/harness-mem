---
name: "HM: Status"
description: 通过 MCP 查看当前项目的健康度和下一步建议
category: Memory
tags: [harness-mem, status]
---

通过 MCP 显示当前项目的记忆状态，并给出 slash-first 下一步建议。

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
   - `phase` / `suggested_slash` / `reason`
4. 用自然语言总结给用户，并给出具体可点的 slash 建议：
   - `phase=needs-distill` → 建议用户跑 `/hm:distill`
   - `phase=ready` → 建议 `/hm:wake`
   - 如果 MCP 还返回 `repair_hint=/hm:review`，把它表述成显式复查/纠错入口，不要把 review 说成日常必经步骤

**Notes**

- 不修改任何状态，只读
- 不要求用户手动运行 CLI；CLI 只作为开发者排障兜底
