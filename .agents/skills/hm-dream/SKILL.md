---
name: hm-dream
description: Run the harness-mem dream daily action when the user invokes hm-dream.
---

# hm-dream

This is a user-invocable harness-mem Daily command. Follow the action below through the configured harness-mem MCP server; do not replace it with terminal maintenance commands.

通过 MCP 查看 0.9.25 DreamRun 账本，或在用户明确要求时触发一次项目级 Dream 治理。

**Input**: 可指定项目名（`$hm-dream bazi-apps`）。省略则用 active project。

**Default UX**

默认 `$hm-dream` 是只读账本视图：展示最近一次 DreamRun 做了什么、为什么、是否失败、如何撤销。不要把 flags 或底层 CLI 参数作为用户主体验。

用户追问时用自然语言 drilldown：

```text
看第 2 条为什么这么处理
撤销第 2 条
展开上一场梦
只看失败项
现在跑一次 dream
```

**Steps**

1. **确认项目**
   - slash 后给了项目名直接用
   - 否则调 MCP `get_project_status(project_root=<当前工作区>, host_client="codex")` 读取 active project，并幂等检查项目 Hook
   - 仍无法确定时，问用户项目名

2. **默认读取最近账本**
   - 调 MCP `dream_ledger`：
     - `project_name=<project>`
   - 如果没有账本，说明还没有已记录的 DreamRun；自动 tick 仍需项目选择用户 profile、启用 autonomous execution 并通过 Dream gate。显式运行不会改写这些授权。

3. **展示摘要**
   - 按 `applied` / `rejected` / `archived` / `failed` 分组
   - 显示处理数量、失败数、policy reason、关键 evidence id
   - 明确自动项不留下 `pending_review`；它必须进入一个终态

4. **自然语言 drilldown**
   - 用户问某条原因：继续读取同一 `DreamRun`，解释该 item 的 evidence、risk、proposed action、final action、reason
   - 用户说“只看失败项”：过滤 `final_action=failed`
   - 用户说“展开上一场梦”：用 MCP `dream_ledger` 读取指定 `run_id` 或最近账本

5. **用户明确要求跑一次**
   - 调 MCP `dream_run`：
     - `project_name=<project>`
   - 返回新 DreamRun 摘要
   - 说明这是显式触发，不代表开启 always-on daemon

6. **用户明确要求自动 tick**
   - 只有当用户问“检查是否该自动跑 / 跑一次 dream auto tick”时，调 MCP `dream_auto_tick`
   - 解释 tick 可能因为用户显式设置了 `dream.auto.enabled=false`、没有活动、未到间隔而跳过

7. **撤销**
   - 用户说“撤销第 N 条”时，先把 N 映射到当前 DreamRun item id
   - 调 MCP `undo_dream_item`：
     - `project_name=<project>`
     - `run_id=<current-run-id>`
     - `item_id=<dream-item-id>`
   - 返回撤销结果和恢复后的状态

**Notes**

- `$hm-dream` 不制造人工 review 队列；高风险 dream 结果按 policy 自动 reject/archive/fail。
- 不 hard delete confirmed truth；需要改变 truth 时保留 audit、evidence、policy reason 和 undo metadata。
- CLI 只作为实现与排障层。用户日常入口是 `$hm-dream`、自然语言和 Agent 背后的 MCP。
