---
name: "HM: Search All"
description: 跨项目搜索记忆，找其它项目里可借鉴的决策、经验和证据
category: Memory
tags: [harness-mem, search, cross-project]
wireFormatVersion: hm-wire-v3.5
---

调用 MCP `search_memory` 做显式跨项目搜索，把结果按项目分组呈现，方便借鉴而不是混淆默认 wake。

**Input**: 必填 query；可选当前项目名（`/hm:search-all bazi-apps "JWT 刷新策略"`）。如果只给一个参数当 query 处理。

**Steps**

1. **确认当前项目**：从 slash 参数或 MCP `get_project_status(project_root=<当前工作区>, host_client="claude-code")` 的 active project
2. **调 MCP search_memory**：
   - `project_name=<current project>`
   - `query=<用户输入>`
   - `mode=auto`
   - `scope=all`
3. **按项目分组呈现结果**：
   - 先列 `current project` 命中
   - 再列 `other projects worth borrowing from`
   - 每条结果带项目名、标题和陈述；不展示内部 ID、评分或原始会话片段
4. **强调可迁移边界**：
   - 明确提示这些是“可借鉴历史”，不是自动写回当前项目的 truth
   - 如果其它项目命中更强，指出值得复用的决策、坑点或流程
5. **给出下一步 hint**：
   - 只想继续深挖某个项目证据：显式使用 `deep_recall=true`、timeline 或 observations drilldown
   - 如果用户想找可复用流程而不是事实决策，再考虑 `search_skills(include_shared=true)`

**Notes**

- 这是显式跨项目搜索入口；不要把跨项目结果默认塞进 `/hm:wake`
- 不改任何状态，只读
- 如果结果为空，提示用户换更具体的主题词，或先对相关项目跑 `/hm:distill`
