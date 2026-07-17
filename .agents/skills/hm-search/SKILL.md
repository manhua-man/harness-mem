---
name: hm-search
description: Run the harness-mem search daily action when the user invokes hm-search.
---

# hm-search

This is a user-invocable harness-mem Daily command. Follow the action below through the configured harness-mem MCP server; do not replace it with terminal maintenance commands.

调用 MCP `search_memory` 工具搜过去说过什么，把结果以可读形式呈现。

**Input**: 必填 query；可选项目名（`$hm-search bazi-apps "JWT"`）。如果只给一个参数当 query 处理。

**Steps**

1. **确认项目**：从 slash 参数或 MCP `get_project_status(project_root=<当前工作区>, host_client="codex")` 的 active project
2. **调 MCP search_memory**：
   - `project_name=<project>`
   - `query=<用户输入>`
   - `mode=auto`（embedding 不可用时自动回退 FTS）
   - `scope=project`
3. **呈现结果**：
   - memory entries 部分按 `[category/memory_type] content (score, mode)` 列
   - observations 部分按 `obs_id session_id preview (score)` 列
   - 头部带 effective_mode 和 fallback_reason

**Notes**

- 不改任何状态，只读
- 这个命令默认只查当前项目；如果用户明确想跨项目借鉴，改用 `$hm-search-all`
- 如果结果为空，提示用户可以先跑 `$hm-distill` 灌历史
- 不要求用户手动运行 CLI；CLI 只作为开发者排障兜底
