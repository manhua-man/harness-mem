---
name: "HM: Status"
description: 通过 MCP 查看当前项目的健康度和下一步建议
category: Memory
tags: [harness-mem, status]
wireFormatVersion: hm-wire-v3.5
---

通过 MCP 显示当前项目的记忆状态，并给出 slash-first 下一步建议。

**Input**: 可指定项目（`/hm-status bazi-apps`），省略则用 active project。

**Steps**

1. 调 MCP `get_project_status(project_root=<当前工作区>, host_client="opencode")`（带项目参数如果有；省略项目名时按目录解析）
2. 解析结果，重点关注：
   - Observations / Memory entries / Confirmed rules 数量
   - Pending candidates 数量
   - `phase` / `suggested_slash` / `reason`
   - 可选 `repair_hint` / `repair_reason`
   - `runtime_versions` / `job_health` / `retrieval_health`
   - `cost_budget` 最近高成本调用与建议
   - `install_drift` stale registration / 旧 slash command 风险
3. 用自然语言总结给用户，并给出具体可点的 slash 建议：
   - `phase=needs-distill` → 建议用户跑 `/hm-distill`
   - `phase=ready` → 建议 `/hm-wake`
   - 如果 MCP 还返回 `repair_hint=/hm-review`，把它表述成显式复查/纠错入口，不要把 review 说成日常必经步骤

4. 只有用户明确追问 provenance、老 pending 细节或最近历史时，才继续调更低层读取面：
   - `timeline`
   - `list_candidates`
   - 其他只读 drilldown 工具
   默认 `/hm-status` 不需要为了给下一步建议而手工拼这些低层工具。

**Notes**

- 状态主体只读；首次调用会幂等创建项目 profile 并安装当前宿主 Hook，不覆盖已有文件
- 不要求用户手动运行 CLI；CLI 只作为开发者排障兜底
