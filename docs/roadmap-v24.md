# Roadmap: harness-mem v2.4

> 状态：已完成，并已由 `v2.4.3` 收口发版。前置 v2.3 (Signals + Suggestion Pass) 已完成。
>
> 主题：Host-triggered Reflection + Queue Health。吸收 `claude-mem` 的运行时韧性，但不照搬「产品内置 always-on daemon / 默认 IDE hook」。

---

## 目标

v2.4 让 reflection、distill、metabolism 这类较重任务有清晰的 job 生命周期和健康检查。

## 当前真值

- `ReflectionJob` schema、lease、idempotent `reflection_once(...)`、host entry、MCP `list_reflection_jobs` / `get_reflection_job`、doctor queue health 已落地并覆盖测试。
- 默认行为仍然是 opt-in host trigger：`triggers.* = off` 时零副作用；`distill.mode=defer_to_agent` 时只走到 `needs_distill`，不会静默调用 LLM。
- v2.4 的业务命令共享实现位于 `harness_mem.commands.reflection_jobs`；hook/host 入口走 `python -m harness_mem.host_entry`，不走 `harness-mem reflection` 这类 CLI 业务子命令。
- 下文保留的是 v2.4 规划与边界说明，作为已实现版本的设计记录。

这一版不追求「默认自动随手记」，而是：

1. 定义安全的 **host-triggered reflection**：由 user、Agent workflow、IDE hook、外部 scheduler **在配置允许时**触发；未启用时零副作用。
2. 人用 **CLI 维护子命令** 管配置、生成 hook；hook/cron 只触发 **业务命令**（`python -m` 或 MCP，见下），**不跑 `harness-mem` CLI**。
3. 失败可见、可诊断、可重试；**不阻断**当前编码主任务。

---

## 术语：CLI、维护子命令、业务命令

三者不要混用：

| 概念 | 是什么 | 例子 |
|---|---|---|
| **CLI** | 终端里的 `harness-mem` 程序（Click/Typer 子命令树） | 仅 v2.4 规划的**维护面** |
| **维护子命令** | CLI 下的子命令，管安装与配置 | `harness-mem config set`、`integration install-cursor-hook`、`doctor` |
| **业务命令** | 记忆运行时里的**具名操作**（Python 共享实现上的函数/任务，不是 CLI 子命令） | `reflection_once`、`ingest_for_project`（名以实现为准） |

**业务命令 ≠ `harness-mem` 的某个子命令。** v2.4 不为 hook 新增 `harness-mem reflection` 这类「业务向 CLI」；hook/cron 通过下面方式调用业务命令：

- `python -m harness_mem.host_entry --project-root … --source ide_hook [--trigger-id … --session-ids …]`（推荐：无 Click 的模块入口；scheduler 场景把 `--source` 换成 `scheduler`），或
- 极短的 stub 脚本 `import harness_mem...; reflection_once(...)`，或
- 已有 Agent 会话时走 **MCP tool**（tool 内部映射到同一业务命令实现）。

**人在终端**改配置、装 hook：只用 **维护子命令**（CLI）。**hook/cron** 只触发 **业务命令**（模块/MCP），**不执行任何 `harness-mem …` 行**（避免把运行时绑死在 CLI 可执行文件上，便于将来去掉 CLI 包仍保留记忆能力）。

## 实现约束（避免重复逻辑）

- **共享实现**：每个业务命令对应 `commands/` / service 层里的可调用入口；MCP handler 与 `python -m` host 入口都只调这里，**不在 `cli.py` 实现业务**。
- **MCP**：IDE 内 Agent → tool → 业务命令实现。
- **Host 触发**：hook/cron → `python -m`（或 stub）→ 业务命令实现；**禁止** hook 调用 `harness-mem`（无论维护还是假想中的业务子命令）。
- 可选：hook 环境有 Agent 时走 MCP，仍映射到同一业务命令实现。

**长驻 worker gate**：仅 `worker.mode=on` opt-in；默认不做 always-on daemon，也不提供
默认后台安装器。

---

## 配置落盘与合并

| 文件 | 作用 |
|---|---|
| `~/.harness-mem/config.toml` | 用户级默认：是否允许 host 触发、distill 策略、限流等 |
| `<repo>/.harness-mem.toml` | 项目级覆盖：`triggers.*`、`distill.mode`、`worker.mode` 等 |
| `~/.harness-mem/data/` | 记忆与 job 数据（不变） |

**合并顺序**（host 触发入口与 `harness-mem config validate` 共用）：

```text
load ~/.harness-mem/config.toml
if exists(<repo>/.harness-mem.toml): deep-merge 覆盖
validate/fill recognized keys: triggers.after_agent / triggers.scheduler / distill.mode / worker.mode
preserve unrecognized tables in extras
```

**CLI 在本版的角色**

- 仅 **维护子命令**（人使用）：`config *`、`integration install-*`、`doctor`、`purge`、`quickstart` 等。
- **不**在 CLI 上暴露业务命令；业务命令只通过 MCP 与 `python -m` host 入口调用。
- `integration install-*` 写入 hook 的必须是 **`python -m harness_mem.host_entry --project-root … --source ide_hook …`**（或文档给出的 stub 路径），**不得**写 `harness-mem config/doctor/…`，也 **不得**写 `harness-mem reflection` 等（v2.4 不提供这类 CLI）。

### 建议配置键（草案）

| 键 | 默认 | 含义 |
|---|---|---|
| `triggers.after_agent` | `off` | `off` \| `on` — IDE 回合结束后是否执行 host 触发脚本 |
| `triggers.scheduler` | `off` | `off` \| `on`（scheduler/cron host trigger gate） |
| `distill.mode` | `defer_to_agent` | 见下表 |
| `worker.mode` | `off` | `off` \| `on`（non-default gate） |

**`distill.mode`（host 触发跑完 ingest/prepare 之后）**

| 值 | 行为 | 是否要再开 Agent |
|---|---|---|
| `defer_to_agent` | 只 ingest + prepare，job 标记 `needs_distill` | **要**：`/hm:distill` 或 MCP + LLM |
| `inline` | 仍由共享 business command 同步推进后续逻辑；当前 v2.4 shipped runtime 尚未把它扩成默认 LLM 主路径 | 视具体实现而定，但当前默认不是这条路径 |
| `worker` | 允许为后续 worker orchestration 预留配置值；当前 shipped runtime 仍未提供默认 always-on worker 主路径 | **不要默认依赖** |

默认 **`defer_to_agent`**。

---

## 示例：Cursor 回合结束（启用时）

前置：`harness-mem integration install-cursor-hook` 写好 hooks；项目 `.harness-mem.toml` 中 `triggers.after_agent = on`；全局默认 `off`。

1. Agent 结束 → hook 执行例如 `python -m harness_mem.host_entry --project-root … --source ide_hook --trigger-id …`（**不是** `harness-mem` CLI）。
2. host 入口读取合并后的 toml；若 `off` 则 exit 0。
3. 否则执行业务命令 `reflection_once`（内部 ingest + prepare、写 job）。
4. `distill.mode = defer_to_agent` 时不跑 LLM；用户稍后再 `/hm:distill`（MCP）。
5. 失败：job 记 failed/retryable，hook **exit 0**，不阻断 Cursor。

---

## 技术来源

- `claude-mem`：CLAIM-CONFIRM queue、worker health、graceful degradation。
- harness-mem v2.3：`RetrievalSignal`、`MetabolismRun`。
- 候选先进 review，不允许静默写 confirmed truth。

---

## Scope

| 领域 | v2.4 决策 |
|---|---|
| Reflection | host-triggered；默认 `triggers.* = off` |
| 触发入口 | MCP（Agent）+ hook/cron（`python -m` host 入口 → 业务命令；不用 CLI） |
| Queue | job lifecycle；不默认常驻 worker |
| Config | 用户级 + 项目级 toml；维护子命令写/校验；hook 只读合并后的 toml |
| Health | doctor 报告 queue / signal / stale candidates |
| Truth | 仅 candidate / suggestion；host 触发不得静默 confirm |
| 主任务 | 记忆失败不阻断 coding（hook exit 0） |

---

## v2.4.0：Reflection Job Model

**用户故事**：触发后要么完成，要么可重试，不能无声卡住。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `ReflectionJob` schema | `pending / processing / completed / failed / retryable`（及 `needs_distill`）；`review` 只是 phase，不是单独 job 类型 |
| P0 | processing lease | 超时 → retryable |
| P0 | job provenance | 来源 `user \| agent \| ide_hook \| scheduler`、project、phase、candidate ids |
| P1 | retry policy | 不重复写相同 candidate |
| P1 | job list/read MCP helper | Agent 可查最近 job 与失败原因 |

---

## v2.4.1：Host-Triggered Reflection Contract

**用户故事**：任务后可自动归档 session；默认不监听每个 turn。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | reflection contract | 四类触发源；行为与 MCP 调用的共享实现一致 |
| P0 | host 入口 | `python -m harness_mem.host_entry` 通过 flags 映射到业务命令；集成测试断言 hook 模板不出现 `harness-mem` 可执行调用 |
| P0 | config merge | 各入口共用 `load_merged_config(project_root)` |
| P0 | no implicit writes tests | 配置为 `off` 时，hook 不产生 job/candidate |
| P0 | output shape | phase、下一步（如 `needs_distill`） |
| P1 | interruption safety | 中断可恢复或明确失败 |

---

## v2.4.2：Queue Health and Doctor

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | doctor queue checks | pending / processing / failed / retryable / needs_distill |
| P0 | stale candidate checks | 长期 pending、高风险项 |
| P0 | signal freshness checks | 最近 signal、 chronic failures |
| P1 | index / WAL hints | maintenance 建议 |
| P1 | health payload for MCP | 结构化 summary |

---

## v2.4.3：CLI Configuration & Integration

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `config set/get/list` | 用户级与项目级 toml |
| P0 | `config validate` | 合并结果可打印 |
| P0 | `integration install-cursor-hook` | 生成 hooks；仅嵌入 `python -m harness_mem.host_entry --project-root … --source ide_hook …` |
| P1 | `integration install-claude-hook` | 同上 |
| P1 | 文档 | 说明 opt-in、默认 off、与 MCP distill 主链关系 |

---

## Non-Goals

- 不把 always-on daemon 作为默认（`worker.mode=on` 也只打开配置 gate，不代表
  提供默认 daemon 安装器或后台主路径）。
- 不默认启用 IDE hook（`triggers.after_agent=off`）。
- 不恢复 v2.0 日常 CLI 工作流（`wake/search/timeline` 等）作为**产品主入口**。
- hook/cron **不得**调用 CLI（`harness-mem`）；记忆动作只通过 **业务命令**（`python -m` host 或 MCP）。
- 不静默写 confirmed truth。
- 不把 File Read Gate 做成默认阻断。
- 不做 cross-project skill（v2.7）。

**可选自动化界线**

- 允许：配置 on + hook 用 `python -m` 触发业务命令（如 `reflection_once`）。
- 不允许：配置 off 时仍写候选；任何入口直接 `confirm_*` 跳过 review。

---

## 后续归宿

| 能力 | 版本 |
|---|---|
| context assembly / Memory Stack | `docs/roadmap-v25.md` |
| wiki / compact index / contradiction | `docs/roadmap-v26.md` |
| cross-project skill | `docs/roadmap-v27.md` |

---

## Release Gate

- `python -m pytest -q`、`ruff`、`mypy`、`openspec validate --all --strict`
- 共享实现契约测试：MCP 与 host 入口对同一 fixture 产生一致 job/ingest 结果
- `triggers.off` 时 hook 无 job 写入
