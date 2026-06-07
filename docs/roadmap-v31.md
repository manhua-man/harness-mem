# Roadmap: harness-mem v3.1

> 状态：已发布，当前版本 3.1.0。
>
> 主题：Auto Dream Memory Maintenance。把 v2.3 signals / metabolism、
> v2.4 reflection job、v2.6 contradiction suggestions 组合成可配置的自动梦境维护机制。

---

## 目标

v3.1 的目标不是再给用户增加一个 review 队列，而是让记忆库在用户开启后可以自动维护自己：

```text
auto dream scheduler
-> DreamRun
-> parse every dream item
-> handle every parsed result
-> write audit / undo metadata
-> expose one simple /hm:dream ledger
```

用户不需要处理 pending dream items。系统必须自动解析所有梦境结果，并把每一条归入一个终态：

| 终态 | 含义 |
|---|---|
| `applied` | 已自动应用，例如 merge / supersede / stale / skill retire |
| `rejected` | 已自动拒绝，例如无证据、噪声、低质量 suggestion |
| `archived` | 已归档为 dream-only record，不进入 truth |
| `failed` | 处理失败，带错误原因和可重试信息 |

没有 `pending_review`。高风险不交给用户确认，而是由策略自动降级处理：证据不足就 reject；无法安全落地就 archive；可安全保留历史的冲突就 supersede。

---

## 用户入口

用户只需要一个入口：

```text
/hm:dream
```

不要把 flags 作为主 UX。底层可以保留参数供 Agent drilldown，但用户文档只教 `/hm:dream`。用户追问时用自然语言：

```text
看第 2 条为什么这么处理
撤销第 2 条
展开上一场梦
只看失败项
```

默认 `/hm:dream` 输出最近一次梦境账本：

```text
最近一次梦境
- 处理: 18
- 自动应用: 7
- 自动拒绝: 6
- 仅归档: 4
- 失败: 1

关键处理
1. merged mem_a + mem_b
2. superseded rule_x with rule_y
3. retired skill_release_old
4. rejected stale claim without evidence
```

---

## 配置

默认关闭。用户显式开启后才自动跑。

```toml
[dream.auto]
enabled = false
trigger = "idle_or_interval"
min_interval_hours = 24
idle_seconds = 900
max_runtime_seconds = 120

[dream.parse]
parse_all = true
require_evidence = true

[dream.handle]
handle_all = true
auto_apply = true
auto_reject_uncertain = true
auto_archive_unclassifiable = true
allow_supersede = true
allow_merge = true
allow_mark_stale = true
allow_retire_skill = true
allow_delete_truth = false
preserve_audit = true
undo_window_days = 30
```

核心边界：

- 默认 `enabled=false`。
- 开启后自动解析所有梦境结果。
- 开启后自动处理所有解析结果，不产生待确认队列。
- 不 hard delete confirmed truth；冲突用 supersede / historical 记录保留历史。
- 自动 merge / stale / supersede / retire / reject / archive 都必须写 DreamRun 审计。
- `/hm:dream` 必须能解释每个处理的 evidence、policy reason 和 undo path。

---

## v3.1.0：Dream Config and Status

**用户故事**：用户可以通过配置开启自动梦境维护，但默认安装不会自动跑。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | config schema | 支持 `[dream.auto]`、`[dream.parse]`、`[dream.handle]` |
| P0 | default off | 未配置时不会 enqueue dream job |
| P0 | doctor visibility | doctor 显示 dream enabled、last run、next eligible time |
| P1 | config validation | 拒绝 `parse_all=false` 或 `handle_all=false` 这类与 v3.1 UX 冲突的配置 |

## v3.1.1：Auto Dream Scheduler

**用户故事**：用户开启后，系统在空闲或到达间隔时自动排队一次 dream job。

优先运行载体：

- 首选 Claude / Cursor / Codex 等客户端或 host 的定时触发能力来调用 `harness_mem`。
- 第一阶段不要求独立后台 dream daemon；调度可以只是 opt-in client task / host scheduler。
- 如果宿主侧没有合适的定时能力，再退回外部 scheduler 或后续服务化评估。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | scheduler gate | `min_interval_hours`、`idle_seconds`、`max_runtime_seconds` 生效 |
| P0 | ReflectionJob integration | enqueue `ReflectionJob(kind="dream")` 或兼容等价 job kind |
| P0 | non-blocking failure | 调度失败只进入 status / doctor，不阻断 wake/search/distill |
| P1 | project activity gate | 没有最近活动的项目不浪费 dream run |

## v3.1.2：Parse Every Dream

**用户故事**：每次 DreamRun 里的每个 item 都会被解释，而不是留下 unparsed 队列。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | DreamRun schema | 记录 input window、parsed items、handling summary、duration、policy version |
| P0 | DreamItem schema | 每条包含 evidence ids、risk、proposed action、final action、reason |
| P0 | parse-all contract | 所有 selected items 都有 final parse result |
| P1 | no hidden summary truth | dream summary 不进入默认 wake/search truth |

## v3.1.3：Handle Every Dream Result

**用户故事**：DreamRun 结束时没有待确认项；每条结果都有自动终态。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | apply merge | 重复 memory 自动合并或标记 duplicate，保留 source chain |
| P0 | apply stale | 长期未 surface 的 truth 自动 stale / historical |
| P0 | apply supersede | 新旧冲突自动 supersede，旧版本可查 |
| P0 | reject uncertain | 证据不足或无法归类的 suggestion 自动 rejected / archived |
| P0 | retire skill | 低成功率 skill 自动 retire 或降权，保留 result history |
| P1 | no pending queue | DreamRun 完成后 `pending_review=0` |

## v3.1.4：Dream Ledger UX

**用户故事**：用户只运行 `/hm:dream`，就能看到最近一次梦境做了什么、为什么、怎么撤销。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `/hm:dream` command | 单入口展示最近一次 DreamRun |
| P0 | natural drilldown | 用户可用自然语言追问某条处理原因 |
| P0 | status integration | `/hm:status` 只提示最近 dream 状态和失败数，不制造待办队列 |
| P1 | concise output | 默认按 applied / rejected / archived / failed 分组摘要 |

## v3.1.5：Undo and Safety Regression

**用户故事**：自动维护不需要用户确认，但每一步都可审计、可解释、可撤销。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | undo metadata | 每个 applied action 都记录 undo path |
| P0 | no hard delete | 测试证明不会 hard delete confirmed truth / observations |
| P0 | wake boundary | dream-only records、archived items、summaries 不进入默认 wake/search |
| P0 | audit replay | 能从 DreamRun 回放 evidence -> parse -> action -> result |
| P1 | failure retry | failed item 能在下一次 DreamRun 里按 policy 重试或归档 |

---

## Release Gate

- `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy harness_mem`
- `openspec validate --all --strict`
- Focused tests:
  - default-off no job
  - scheduler gate
  - parse-all contract
  - handle-all final states
  - no pending dream review queue
  - no hard delete
  - `/hm:dream` single-entry UX
  - audit replay / undo metadata

---

## 一句话

v3.1 的梦境机制不是“生成待办给用户审”，而是自动维护记忆库：自动做梦、自动解析、自动处理全部结果；用户只在想看的时候通过 `/hm:dream` 查看梦境账本，或撤销某次处理。
