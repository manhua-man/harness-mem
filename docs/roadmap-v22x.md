# Roadmap: harness-mem v2.2.x

> 状态：规划中。v2.2 是 v2.1 surface 瘦身之后的用户入口与客户端互通版本。
>
> 主题：让 Slash / Skill / 自然语言入口真的可用，用户不需要知道 CLI 子命令或 MCP tool name。

---

## 一句话目标

v2.2 要让 `harness-mem` 体感上成为 AI IDE 里的记忆运行时，而不是一堆隐藏工具：
`/hm:distill`、`/hm:wake`、`/hm:search` 以及等价自然语言指令，应该能在 Claude Code、Codex、Cursor 和通用 MCP client 中跑完整闭环。

---

## 为什么先做 v2.2，而不是直接做代谢

v2.1 已经砍掉误导性 surface：日常 CLI 命令和 REST API 不再是产品路径，MCP 被明确降到 Agent 背后的传输层。下一步风险不是“算法不够聪明”，而是“文档说用户不用碰 CLI/MCP，但真实客户端里 Agent 还是会滑回 CLI/MCP 名字”。

所以 v2.2 不新增记忆模型。它稳定用户可见工作流：

- 用户给短命令或自然语言请求
- Agent 解析项目
- Agent 准备 evidence packet
- Agent 写候选
- Agent 自动审核低风险项
- 用户只看到简洁摘要和少数高风险残留

如果这条链不稳，v2.3 / v2.4 做再强的内部能力，也只会制造更多用户够不到、审不动的候选。

---

## Scope

| 领域 | v2.2 决策 |
|---|---|
| 用户入口 | IDE command / Skill / 自然语言优先 |
| MCP | Agent 背后的隐藏传输层，不作为用户指令 |
| CLI | 只做 maintenance；不恢复日常命令 |
| REST API | 不恢复 |
| 记忆语义 | 不新增 truth model |
| 候选写入 | 只发生在显式流程 |
| daemon / hook | v2.2 不做 |

---

## 切片

### v2.2.0：Golden Path Contract

**用户故事**：我可以说“用 harness-mem 整理最近 10 个 session”或运行 `/hm:distill`，Agent 会完成闭环，而不是让我去终端敲 CLI。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | 统一 `/hm:distill`、`/hm:wake`、`/hm:search`、`/hm:review` 与自然语言等价入口 | `plugins/harness-mem/commands/hm/*.md`、`plugins/harness-mem/skills/harness-mem/SKILL.md`、`README.md`、`AGENTS.md` 使用同一套口径，不把 CLI/MCP 名字当用户指令 |
| P0 | 项目解析契约 | Agent 优先用 active project / project profile，其次当前 workspace root，最后只问一个短问题；绝不提示用户运行 `harness-mem use` |
| P0 | Distill 闭环契约 | `/hm:distill` 路径固定为 `prepare_session_distill -> session-distill -> suggest_* -> list_candidates -> auto-review/confirm/reject -> summary` |
| P0 | 失败契约 | MCP 不可用、LLM agent 不可用、evidence packet 为空、project mismatch、权限问题，各自有一句用户可懂提示和一条开发者排障指针 |
| P1 | 摘要格式契约 | distill 最终输出固定包含：ingested / candidates / auto-confirmed / auto-rejected / pending / high-risk |
| P1 | `/hm:review` 定位 | review 是复查/修复入口，不是每次 distill 后的必经步骤 |
| P2 | 客户端示例 | README 各给一个 Claude Code slash、Codex agent prompt、Cursor 自然语言 prompt、通用 MCP client 设置示例 |

### v2.2.1：Cross-Client Test Packet

**用户故事**：我们能证明自己支持的客户端真的能跑通，而不是只在一个 happy path dogfood。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | 把 `docs/v2-user-test-packet.md` 升级为 v2.2 client test matrix | Claude Code、Codex、Cursor、通用 MCP client 各有 setup、action、expected output、failure classification |
| P0 | 增加“agent without CLI” loop harness 场景 | 测试断言 project setup、wake、search、candidate review 可以通过 MCP/runtime helper 驱动，不调用已移除的日常 CLI 子命令 |
| P0 | 增加 stale-doc detector | README / AGENTS / plugin commands 如果重新把 `harness-mem wake/search/timeline/candidates` 写成用户日常命令，测试或 focused scan 失败 |
| P1 | MCP alias 指南 | 当客户端暴露 raw tools 时，插件文档统一推荐稳定 alias；但正常用户指令仍不展示 tool names |
| P1 | Cursor / Codex parity notes | 客户端差异记录为 docs/prompt 修复，不留成口头知识 |

### v2.2.2：Auto-Review UX Hardening

**用户故事**：AI 处理无聊的候选审核工作，我只看真正需要判断的少数项。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | 低风险 auto-review policy | 把 confirm / reject / defer 判断标准写成一个共享文档，被 `/hm:distill` 和 Skill 流程复用 |
| P0 | evidence-grounded auto-confirm | 自动确认的记忆必须带 source observation/session id；证据弱的候选只能 pending 或 reject |
| P0 | 噪声拒绝 fixture | 覆盖工具故障、跨项目 workflow 泄漏、泛泛生产力建议、重复候选、把 distill 过程误写成项目事实 |
| P1 | 高风险 pending surface | 最终摘要区分“静默保留 pending”和“需要你确认” |
| P1 | 可追溯解释 | 用户问“为什么确认/拒绝这条”时，Agent 能给出 candidate id、evidence id 和采用的规则 |

---

## Non-Goals

v2.2 明确不做：

- Memory Metabolism / Dream
- 跨项目 Skill sharing
- procedural skill 默认注入 wake
- 后台 daemon / IDE hook / turn-end 自检
- AI 自治改 truth 或删除 truth
- REST API 恢复
- 日常 CLI 命令恢复

---

## Release Gate

v2.2 发布前必须满足：

- full `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy harness_mem`
- `openspec validate --all --strict`
- removed daily CLI command 的 stale surface scan
- v2.2 client test packet 至少跑 Claude Code + 一个非 Claude client

