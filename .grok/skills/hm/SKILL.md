---
name: hm
description: Use harness-mem to remember this session, find prior work, or correct memory.
metadata:
  wireFormatVersion: hm-wire-v3.5
---

# hm

这是 harness-mem 唯一的日常入口。根据用户正在说的话直接处理，不要让用户再选内部动作，也不要默认展示 job、candidate、receipt、provider、内部 ID 或 MCP 工具名。

始终使用用户当前使用的语言回复；用户切换语言时跟随最新一句，不要因为下面的中文示例固定输出语言。

处理请求前，先调用：

`get_project_status(project_root=<当前工作区的绝对路径>, host_client=<当前 Agent 宿主>, detail_level="compact")`

必须显式传入 `project_root` 和 `host_client`。这一步会在该项目第一次使用时准备项目与 Hook；它不安装 MCP，也不重装全局入口。若准备 Hook 失败，直接说明失败位置和一个最短修复动作，不要声称已经准备完成。

- “记住这次”：在当前项目调用 `prepare_session_distill(client="auto", scope="project", project_root=<当前项目根目录>, evidence_mode="semantic", detail_level="compact")`，完整阅读返回的会话内容；只为有长期价值且证据成立的窄知识点调用 `govern_memory(action="suggest")`，未完成事项用 `govern_memory(action="handoff")`，最后必须调用 `finalize_session_distill`。不能把 `completed` 当作已经记住的证明。
- “找一下以前怎么做的”：调用 `search_memory`，默认只查当前项目；只有用户明确要求跨项目时才用 `scope="all"`。
- “这条记忆不对”：先定位用户指的当前知识；变更明确后用 `govern_memory(action="decide")` 提交纠正、替换或撤销，不修改无关记忆。如果无法确定是哪一条，只问一个最短问题。

项目名按当前工作区解析。MCP 不可用时，只给一个最短恢复动作：请在当前 Agent 或 Router 中连接 `harness-mem-mcp`，新开一个任务后重试。不要改走另一套终端记忆流程。

只把用户需要知道的结果说清楚：

```text
记住了：<具体内容；没有则写“没有需要长期记住的内容”>
没记：<被跳过的内容及普通原因；没有则省略>
还没完成：<未完成事项；没有则省略>
```

用户使用英文或其他语言时，用同样简短的本地化标签。搜索或纠正时直接给结果，不补一套产品术语。
