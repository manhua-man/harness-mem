# 设计/UX 评审：harness-mem v1.2.0

> 评审日期：2026-04-25 | 评审范围：CLI 交互 + MCP Server + wake-up 输出

---

## 1. CLI 命令体系的一致性

### 达标的方面

- 短别名体系（`wake`/`tl`/`ds`/`qs`/`st`）覆盖了高频操作，降低了日常输入负担
- 参数命名统一：`-p`/`--project`、`-n`/`--limit`、`-s`/`--session-id` 在多个命令间保持一致
- `doctor` + `quickstart` 的"状态感知→建议下一步"模式是 CLI 设计的最大亮点

### 不一致与认知负担

| 问题 | 位置（`harness_mem/cli.py`） | 分析与建议 |
|------|-------------------------------|-----------|
| `search` 的 `--query` vs `show` 的 `--id` | 行 364-380 | `search` 用 `query_arg` 位置参数 + `-q`/`--query` 命名参数；`show` 用 `observation_id_arg` 位置参数 + `-i`/`--id`。命名风格不对齐。建议 `show` 改为 `-o`/`--observation-id` |
| `correct` 和 `handoff` 的交互式与非交互式路径混合在 `main()` 中 | 行 502-571 | 交互式回退逻辑与主 dispatch 耦合紧密。建议将每个命令的交互式模式提取到 `_interactive_*()` 函数 |
| `ingest` 的 `client` 是位置参数 | 行 348 | 默认值 `claude-code` 合理，但首次用户可能不知道位置参数的存在。帮助文本应更显式 |
| `list-candidates` 和 `confirmed-rules` 命令名过长 | 行 422-430 | 别名已覆盖（`candidates`/`rules`），长名可以保留但建议 README 突出显示别名 |

---

## 2. wake-up 输出结构评估

### 当前结构

```
# Project Profile  (source: profile, ~N chars)
# Recent Tasks  (source: task_handoffs, N items, ~N chars)
# Confirmed Rules  (source: confirmed_rules, N rules, ~N chars)
# Memory Entries  (source: structured_memory, N entries, ~N chars)
Approx wake-up tokens: ≈ N [Lx]
Compact suggestion: ...
```

### 分块评价

| 维度 | 评价 |
|------|------|
| **区块划分** | 四块合理。按"静态 profile → 动态任务 → 固化规则 → 新增记忆"的优先级排序正确 |
| **来源注释** | v1.2.0 加的 `(source: ...)` + char count 很好，对 LLM debug 和 token 追踪都有帮助 |
| **Token 预算** | 末尾单行 + level + compact 建议，信息密度合理 |
| **空数据处理** | v1.2.0 统一用 `(source: ..., empty)` 而非跳过 -- 正确方向。结构一致性比美观更重要 |
| **截断标记** | `content[:100]` / `content[:150]` 截断没有标记。当 LLM 消费 wake-up 输出时，被截断的信息可能产生误导。建议追加 `[...truncated]` |

### 问题

- **预算明细不透明**：`wake-up` 只给总数，但 `profile` 和 `status` 命令有各层明细。建议在底部加一行简略比例：`Profile: ~N | Entries: ~N | Rules: ~N | Handoffs: ~N`
- **LLM 优化程度**：区块顺序是按"重要度"排列，但 LLM 更偏好在**开头**看到最重要的信息。目前的顺序（profile → tasks → rules → entries）已经是合理的，但 rules 在 entries 之前的理由需要验证：规则通常比单条记忆条目更关键

---

## 3. MCP Server 工具设计

### 已覆盖工具（9个）

`search_memory` | `timeline` | `get_observations` | `get_task_handoffs` | `get_confirmed_rules` | `get_project_profile` | `create_rule_candidate` | `confirm_rule`

### 不足

| 缺失 | 影响 | 优先级 |
|------|------|--------|
| **`reject_rule_candidate`** | CLI 有 `reject-rule`，MCP 没有对应的 reject 工具。不对称 | P0 - v1.3 |
| `get_memory_entries`（直接 list） | 目前只能通过 `search_memory` 间接读，缺少直接列表入口 | P1 |
| `distill` 触发 | MCP 只能读已蒸馏的记忆，不能触发蒸馏流程 | P2 |
| cross-project search | 所有工具都要求 `project_name`，没有跨项目统一入口 | P3 |

---

## 4. v1.3/v1.4 UX 优先改善项

1. **MCP reject_rule 不对称** — CLI 有完整 CRUD，MCP 只有 create + confirm。v1.3 必须补齐
2. **wake-up 截断标记** — 在 content[:100] 等截断处加上 `[...truncated]` 标记，避免 LLM 误解
3. **`profile --edit` 的列表编辑 UX** — `_prompt_list_labeled` 需逐行输入，已有 10+ items 时体验不好。建议支持逗号分隔的一次性输入
4. **`search` 结果排序透明度** — 当前结果没有排序依据标注，用户不理解为什么某条排在前。建议追加 `(score: 0.85)` 等评分标注
5. **`doctor` 状态解释** — 给出命令建议时，不解释"为什么处于这个阶段"。建议加一句简短状态描述，如 `Phase: ingestion complete → ready for distillation`

---

## 5. CLI Design Expert 准则达标情况

| 准则 | 状态 | 说明 |
|------|------|------|
| 1. 默认优先 | 通过 | active project、自动 session 发现均已实现 |
| 2. 一步一引导 | 通过 | quickstart + doctor 建议链清晰 |
| 3. 渐进披露 | 部分通过 | 交互式模式覆盖 correct/handoff，但非交互式下的错误信息可以更有帮助（现在直接 parser.error） |
| 4. 状态感知 | 通过 | 四状态判断（0 obs / obs no memory / memory no structure / ready）合理 |
| 5. 输出三问题 | **未通过** | 回答了"发现什么"和"下一步"，但"处在闭环哪一阶段"需要用户自行将计数映射到阶段图 |
| Review Checklist 第5条 | **未通过** | 没有明确解释 distill 和 wake 为什么适应当前阶段状态 |
