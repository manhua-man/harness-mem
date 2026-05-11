# harness-mem v1.3 & v1.4 路线图提案

> 基于 八 方评审综合形成（CEO/战略、Eng/工程、Design/UX、DevEx、CLI 专家、Office Hours、Health 仪表盘、Linus 代码审查）。
> 评审日期：2026-04-25 | 基线版本：v1.2.0
> 状态更新：2026-05-11（基于当前仓库实现、OpenSpec 归档状态与测试结果回填）

---

## 核心判断

**v1.3 + v1.4 = V1 体验封口层。不做 V2 大重构，不扩平台，不提前引入 cross-encoder 或 graph DB。**

当前阶段的主要矛盾已从"功能是否存在"转向"功能是否足够可靠、可解释、可维护"。v1.3 和 v1.4 应该让现有用户在每天使用中感觉到"这东西变靠谱了"。八个评审在此方向上高度一致。

> **Office Hours 的警示：** 当前 pain is real but mild。如果 Claude Code 官方内置 memory，80% 价值被吸收。Moat 是 local-first privacy + multi-client + 可审计性，但这些都很 thin。生存策略是拼 integration breadth + data ownership，而非跟官方卷 feature 密度。现阶段不建议过早考虑商业化。

---

## 产品形态原则

这份路线图默认建立在以下产品判断之上：

1. **CLI 是 bootstrap，不是终局形态**  
   CLI 继续保留，因为它适合安装、试用、调试、显式修正和脚本化；但长期成功不应建立在用户持续手动执行 `ingest`、`wake`、`search` 之上。

2. **MCP-first，而不是 UI-first**  
   对当前阶段来说，最值得优先打磨的不是额外界面，而是让 Claude Code / Codex 这类 agent client 更自然地接入同一层本地记忆。主路径应该是默认运行在 agent workflow 中，而不是停留在外部工具模式。

3. **Invisible by default, visible when needed**  
   目标体验是“这个 agent 记住我了”，不是“我在维护一套记忆系统”。但 invisible 不能等于 black box：用户必须始终能回答“记住了什么、为什么被注入、来源是什么、怎么删掉”。

4. **自动化要渐进增强，不要一步黑箱化**  
   顺序应是：自动加载 / 自动发现 session / 轻量 wake-up 建议或注入 / 更强的主动写入与主动推送。只有在准确率和可解释性足够高时，才值得进一步减少显式命令。

5. **问题域是 memory runtime，不是 language server**  
   我们解决的是跨 session 记忆、任务续接、规则学习和上下文恢复，因此 LSP 不是正确抽象层。当前产品路线只保留 MCP 自动化这一条主路径，不再把 VS Code extension、后台 daemon 或 editor integration 作为规划项。

---

## 当前状态快照（2026-05-11）

### v1.3

| 条目 | 当前状态 | 说明 |
|------|----------|------|
| Purge 命令 | 已完成 | CLI、OpenSpec 主规格和主流程文档都已纳入，`purge --before / --dry-run / --category` 已落地 |
| 向量 hybrid 检索 | 已完成 | hybrid 已实现并成为主线能力，LongMemEval 当前最佳 `R@5 = 94.18%`，已达到路线图中的 `94%+` 目标 |
| CLI 体验微调 | 大部分完成 | score、阶段提示、purge 建议、`show` 命名统一、`correct`/`handoff` 输入校验已落地；`cmd_purge`、`cmd_distill`、`cmd_use` 与只读 `cmd_profile` 已迁入 `commands/`，但 `cli.py` 仍有过多 dispatch、兼容入口和交互式逻辑 |
| DevEx 基建与代码卫生 | 大部分完成 | OpenSpec active changes 已清空并归档，`ruff`、`mypy harness_mem`、`python -m pytest -q` 当前通过；最新测试读数为 `174 passed`；剩余是真实使用验证与 hybrid 性能缓存 |

### v1.4

| 条目 | 当前状态 | 说明 |
|------|----------|------|
| Provenance 追溯 | 已完成 | `MemoryEntry`、`TaskHandoff`、`ConfirmedRule` 已有 provenance 字段，CLI/MCP 已开始展示来源线索 |
| Learning Loop MCP 升级 | 已完成 | `reject_rule` 与 `suggest_rule` 已存在，Learning Loop 的 MCP 闭环基本补齐 |
| `cli.py` 拆分 + Adapter Protocol 统一 | 部分完成 | `commands/`、`AdapterRegistry` 与 `SessionAdapter` 已落地；`cmd_purge`、`cmd_distill`、`cmd_use` 与只读 `cmd_profile` 已迁出，`cli.py` 已降到约 839 行，仍需继续瘦身和补契约测试 |
| Relation Facts | V1 闭环已落地 | `RelationFact` schema、structured store 接口、SQLite/本地 JSON 存储、CLI/MCP search、distill 写入与 wake 注入已存在；剩余是 benchmark 证明和更高质量抽取 |
| Temporal Bias | 显式 search 开关已落地 | CLI `search --temporal-bias`、MCP `search_memory.temporal_bias` 与 REST `/search?temporal_bias=true` 可启用同分时间排序；默认仍关闭，等待 benchmark 证明后再考虑默认启用 |
| 记忆质量评分 | 最小闭环已落地 | `MemoryEntry` 已记录 `usage_count` / `last_accessed_at`，search/wake/MCP 返回 entry 时会更新访问计数，`doctor` 会展示 stale / never-accessed 摘要；自动清理策略仍未完成 |

### 阶段判断

- **不是“V1.x 已结束”**，而是：`v1.3 / v1.4` 的 OpenSpec 变更已归档，主规格、测试门与 LongMemEval 检索指标已收口，但记忆质量维护和真实使用证明仍未达标。
- 因此这份路线图当前应被理解为：**能力面和验证链已经进入收口状态，下一步应优先证明记忆质量维护、真实使用留存和 hybrid 检索性能。**
- **下一步优先级：先做 Temporal Bias benchmark，再继续拆 `cli.py`。** Temporal Bias 会影响用户可见 search / wake 结果排序和默认策略，必须先用 benchmark 证明“不隐藏旧但更相关的记忆”；继续拆 `cli.py` 主要降低内部维护成本，可以在 benchmark 结论后按命令模块继续推进。

---

## v1.3 范围（建议 2-3 周）

### P0: Purge 命令（Compact Guard 闭环）

**当前状态（2026-04-27）：已完成。**

| 来源 | 优先级 |
|------|--------|
| CEO: P0 | Eng: Small, 1d | Design: +截断标记 |

**用户痛点：** wake-up 预算到 L3/L4+ 后只能看不能做。doctor 建议 distill 但 distill 只整理不删除。

**实现：**
- `harness-mem purge --before <DATE>` — 删除指定日期前的 verbatim + structured
- `--dry-run` 预览删除数量
- `--category` 限定类型（如只清理 bug 类 memory entries）
- 标记式删除（soft-delete, `compacted: true`），而非物理抹除，保持可逆

**验证：** 删前 budget L4+ → 删后 L2，doctor 确认

---

### P1: 向量嵌入 + FTS5 Hybrid 检索

**当前状态（2026-05-10）：已完成。能力已落地，benchmark 目标已达成。**

| 来源 | 优先级 |
|------|--------|
| CEO: P1（基础设施升级）| Eng: Medium, 2-3d | Benchmark: R@5 87.3% → 目标 94%+ |

**用户痛点：** 同义词、语义变换场景搜不到。multi-session R@5 仅 79.2%，temporal-reasoning 仅 82.8%。

**当前实现：**
1. `search/hybrid_search.py` — `HybridSearchLayer`
   - 模型：`sentence-transformers/all-MiniLM-L6-v2`（384 维，~100MB）
   - lazy load：仅在 hybrid search 时加载，不在 ingest 时阻塞
   - 候选池：FTS 10x 候选 + bounded recent/all-row vector 候选，避免 semantic-only 结果被 FTS 闸门挡住
   - 排序：weighted RRF，`k=40`、`vec_weight=5.0`
   - fallback：无 sentence-transformers 或 embedding 失败时自动退化为纯 FTS
2. `tools/longmemeval.py` — benchmark adapter
   - 默认索引 user turns
   - 对明确追问 assistant 先前回复的 query 纳入 assistant turns，避免 assistant-memory 题被错误排除证据
3. 接口：`search --mode auto|fts|hybrid` 已落地

**不做的：**
- ❌ ReRanker（cross-encoder）— V2 再做，推理成本高
- ❌ ChromaDB — 违反 local-first 原则
- ❌ semantic chunk — V2 再做

**验证目标：** LongMemEval R@5 ≥ 94%  
**当前读数：** 最新最佳配置为 `RRF k=40, vec_weight=5.0, FTS 10x + bounded vector pool`，`R@5 = 94.18%`（`benchmarks/results/results_harness_hybrid_real_allvec_adaptive_top5_20260510_r2.json`），比原始 FTS baseline `87.3%` 提升约 `+6.9pp`。

---

### P1: CLI 体验微调（渐进披露收口）

**当前状态（2026-05-11）：大部分完成。**

| 来源 | 优先级 |
|------|--------|
| CEO: P2 | Design: 多个问题 | CLI Expert: 3 个 P0、5 个 P1-P2 | DevEx: P2 |

**改动清单（低风险、高感知）：**

**P0（来自 CLI Expert 评审）：**

| 问题 | 改动 | 位置 |
|------|------|------|
| `timeline --help` 不显示默认 50 | 把 `default=50` 加到 argparse 参数中 | `cli.py` |
| `search` 无 query 时抛 argparse error | 捕获 `SystemExit` 后输出友好提示 + 列出最近 observation 标题 | `cli.py` |
| `correct`/`handoff` 的 `--help` 不提示交互式 | help 文本标注交互式行为，空白参数不再当作有效值，`handoff --status` 限定到声明状态 | `cli.py`, `cli_commands.py` |

**P1-P2（CLI 专家 + Design 评审）：**

| 问题 | 改动 | 位置 |
|------|------|------|
| wake-up 截断无标记 | content[:N] 后追加 `[...truncated]` | `cli.py cmd_wake_up` |
| search 结果无排序依据 | 追加 `(score: 0.85)` | `cli.py cmd_search` |
| show `--id` 命名不一致 | `-i`/`--id` → `-o`/`--observation-id` | `cli.py` |
| doctor 缺少阶段描述 | 加 `Phase: ...` 行 + 分割线分离诊断与建议 | `cli.py cmd_doctor` |
| 内存膨胀时提示 purge | doctor/wake-up 的 L3/L4+ 建议追加 `harness-mem purge` 示例 | `cli.py` |
| status/profile/wake 无下一步建议 | 尾部追加标准三行：阶段 / 下一步 / 原因 | `cli.py` |
| 0 sessions 时指向 ingest | 改为指向 `quickstart` | `cli.py _suggested_next_step` |
| quickstart 建议视觉不突出 | `==>` 前缀标记下一步 | `cli.py` |

---

### P2: DevEx 基建 + 代码卫生

**当前状态（2026-05-11）：大部分完成。**

| 来源 | 优先级 |
|------|--------|
| DevEx: P0-P2 | Health: lint/type debt + storage test gap | Linus: 多处静默异常 |

**Health review 原始发现（详见 `review-health-v13-v14.md`）：**
- 旧报告记录过 22 个 lint 错误、26 个 type 错误，以及 `local_structured_store.py` / `sqlite_index.py` 缺少直接单元测试。
- 该报告是 review 证据，不再代表当前 checkout 的 live 状态。

**当前 live baseline：**
- `python -m ruff check .` 通过
- `python -m mypy harness_mem` 通过
- `python -m pytest -q` 通过，最新读数 `174 passed`
- `openspec validate --all --strict` 通过，9 specs passed

**改动清单：**
- 跑 `ruff --fix` 并手动收尾剩余 lint
- 修复当前 `mypy harness_mem` 的 adapter/read-api/benchmark 类型错误
- 保留仍被 schema 字段使用的 `Optional` import，不按旧清单误删
- 加固 `correct`/`handoff` 输入校验与项目作用域
- 补齐 `local_structured_store.py` 直接单元测试，扩展 `sqlite_index.py` FTS update / blank query 测试
- Adapter 静默吞异常改为 logging（Linus: "去你的"——`except Exception: pass`）
- `list_project_sessions` 用 `read_text()` 加载整个文件计数行 → 改为 `readline()` 流式（50MB 文件会爆内存）
- Storage layer 单元测试（`local_structured_store.py` + `sqlite_index.py`）
- Adapter 文件不存在时 warning 而非静默空返回
- MCP server smoke test 提升覆盖率
- SQLite 错误包装为用户友好消息（全局异常钩子）

---

## v1.4 范围（建议 2-3 周）

### P0: Provenance 追溯

**当前状态（2026-04-27）：已完成。**

| 来源 | 优先级 |
|------|--------|
| CEO: P0 | Design: 隐含 | DevEx: 未提及 |

**用户痛点：** 看到 distill 产生的规则 / memory entry 后，最多的问题就是"这条从哪来的？"

**实现：**
- 每条 `MemoryEntry`、`ConfirmedRule`、`TaskHandoff` 存储其来源 observation ID
- `harness-mem show <memory-entry-id>` 展示来源 observation 摘要 + session 链接
- wake-up 中每条 rule 标注来源 session ID

**验证：** 100% structured entry 可追溯

---

### P1: Learning Loop MCP 升级

**当前状态（2026-04-27）：已完成。**

| 来源 | 优先级 |
|------|--------|
| CEO: P1 | Design: P0（reject_rule 不对称）| DevEx: 未提及 |

**用户痛点：** correct → confirm/reject 流程要切换终端，MCP 只有 create + confirm 没有 reject。

**实现：**
- 补齐 `reject_rule_candidate` MCP 工具
- 新增 `suggest_rule` MCP 工具：基于当前 session 内容自动检测是否应生成 candidate
- MCP 工具的 cross-project search 入口

**验证：** CLI 与 MCP 功能完全对称

---

### P1: cli.py 拆分 + Adapter Protocol 统一

**当前状态（2026-05-11）：部分完成。**

| 来源 | 优先级 |
|------|--------|
| DevEx: P1 | Eng: 隐含 | Design: 提到交互式模式提取 |

**当前问题：** `commands/`、`AdapterRegistry` 与 `SessionAdapter` 已落地，`cmd_purge`、`cmd_distill`、`cmd_use` 与只读 `cmd_profile` 已迁入 `commands/` 并保留兼容入口，但 `cli.py` 仍约 839 行，仍承担过多 dispatch、兼容入口和交互式逻辑。

**剩余实现：**
- 继续把 `cli.py` 中保留的命令实现、兼容 wrapper 和交互式逻辑迁入 `commands/` 或专用 support 模块
- 为 `SessionAdapter` / `AdapterRegistry` 增加直接契约测试，确保新增 adapter 不再需要散落修改入口文件
- 更新开发文档，明确新增 adapter 的最小文件清单和验证命令

---

### P2: Relation Facts

**当前状态（2026-05-11）：V1 闭环已完成，质量证明未完成。**

| 来源 | 优先级 |
|------|--------|
| Eng: P2 | CEO/Design: 未直接要求 |

**已完成：**
- 新增 `RelationFact` schema，表达 subject / predicate / object / evidence / confidence / tags。
- `StructuredStore`、SQLite index 与本地 JSON store 已支持 save/get/list/search。
- `harness-mem search` 会展示匹配的 RelationFact 结果。
- MCP `search_memory` 返回 `relation_facts` 与 `relation_fact_count`。
- `distill` 会从明确的实体关系句中保守抽取 RelationFact。
- `wake` 会以独立 section 注入最近 5 条 RelationFact，并计入 wake budget。
- 新增直接存储、CLI search、MCP search、distill 与 wake 测试，覆盖基本闭环。

**剩余实现：**
- 用 recall / wake-up usefulness benchmark 证明它比普通 structured memory 有增益。
- 后续如果要提高召回，必须引入更强抽取器或人工确认，不应扩大当前正则启发式。

---

### P2: Temporal Bias

**当前状态（2026-05-11）：显式 search 开关已完成，默认策略未完成。**

| 来源 | 优先级 |
|------|--------|
| Eng: P2 | Health: 质量门槛相关 |

**已完成：**
- `HybridSearchLayer` 支持构造级和 per-call temporal bias，在同分结果中用 observation timestamp、memory updated_at、handoff last_activity、rule created/confirmed 时间做排序。
- CLI `search --temporal-bias`、MCP `search_memory.temporal_bias` 与 REST `/search?temporal_bias=true` 已接入。
- LongMemEval 工具已补 `--temporal-bias` 和 `--compare-temporal-bias`，可以跑真实 hybrid 的 baseline vs temporal-bias 对照，并输出 avg / per-type delta 与 gate 判断。
- `harness_mem.benchmarks` 已补 `daily-wake-temporal-safety` 报告型 gate，wake memory selection 已加入重要性保护，避免旧但关键的 memory 被最近普通条目挤出。
- 默认关闭，避免无 benchmark 证明时把新近内容误当作更相关内容。

**剩余实现：**
- 跑完整 LongMemEval 对照：`python -m harness_mem.tools.longmemeval <data.json> --mode hybrid --use-real-hybrid --compare-temporal-bias --out benchmarks/results/results_harness_hybrid_temporal_compare_top5_<date>.json`。
- 用真实 dogfooding 数据跑 wake gate，确认重要性保护不会让过期高 usage memory 长期占位。
- 决定何时允许默认启用。

---

### P2: 记忆质量评分

**当前状态（2026-05-11）：最小闭环已完成，自动清理策略未完成。**

| 来源 | 优先级 |
|------|--------|
| CEO: P2 | 其余: 未提及 |

**已完成：**
- `MemoryEntry` 增加 `usage_count` 与 `last_accessed_at` 字段。
- CLI search、wake-up 和 MCP `search_memory` 在真正返回 memory entry 时记录访问。
- `doctor` 展示 stale / never-accessed 摘要，形成质量基线。

**剩余实现：**
- 定义低质量 entry 的产品标准，避免只按时间误删仍有价值的旧决策。
- 把自动清理建议接到 `purge --dry-run` 或后续 compaction 评分，而不是直接物理删除。

---

## v1.3 / v1.4 不做的（明确推迟到 V2 / 不承诺）

| 功能 | 理由 | 目标版本 |
|------|------|---------|
| ReRanker（cross-encoder） | ~500MB 模型，推理成本高，在 hybrid R@5 ≥ 94% 后评估 | V2 |
| Graph 记忆（实体关系图） | 复杂度高，V1 用户无此需求信号 | V2 |
| 跨客户端任务续接 | 需协议设计，当前 Claude Code + Codex 各自独立已够用 | V2 |
| Cursor / Gemini adapter | 核心用户在 Claude Code + Codex，扩平台是增长不是留存 | v1.5（保持原计划） |
| Web UI / Dashboard | 不确定用户是否真的需要 web 界面，CLI 是正确的最小交付 | V2+ 观察 |
| VS Code extension / daemon 包装 | 已从当前路线图移除；先把 MCP 自动化、CLI 模块化和 adapter 契约统一做透 | 不规划 |
| LSP server | 已从当前路线图移除；问题域是 memory/runtime orchestration，而不是语言服务 | 不规划 |
| 协作/多用户 | 完全不同的产品 | V3+ 不承诺 |
| Pricing / 商业化 | Office Hours: pain is real but mild，在找到 10 个 daily 用户验证前不要考虑 | 不早于 V2 |
| Protocol 接口删除 | Linus: "只有一个实现就不需要 Protocol"——但 V2 计划引入多后端，保留但不做**新增** | V2 时再评估 |
| 端到端 LLM 蒸馏替换 | Linus: 30 个硬编码正则确实天真，但 LLM 蒸馏会增加依赖和成本。正则 + LLM 回退是 V2 | V2 |

---

## 路线图全景

```
v1.3（~3 周）                    v1.4（~3 周）                    v1.5（计划）
┌────────────────────────────┐  ┌────────────────────────────┐  ┌──────────────┐
│ P0  purge 命令             │  │ P0  Provenance 追溯        │  │ Cursor       │
│ P1  向量 hybrid (R@5≥94%)  │──→│ P1  Learning Loop MCP 升级 │──→│ Gemini CLI   │──→ V2
│ P1  CLI 体验微调           │  │ P1  cli.py 拆分 +          │  │ adapter      │
│ P2  DevEx 基建（测试补齐） │  │     Adapter 协议统一        │  │              │
│                            │  │ P2  记忆质量评分            │  │              │
└────────────────────────────┘  └────────────────────────────┘  └──────────────┘
```

---

## 退出条件（何时 V1.x 可以结束）

1. **检索能力证明：** FTS5 + 向量 hybrid 的 LongMemEval R@5 ≥ 94%
2. **体验完整性证明：** purge → distill → wake-up 闭环无断裂
3. **差异化能力采用率证明：** Learning Loop 的 MCP 使用率 ≥ 30% 新规则
4. **外部验证证明：** 至少 3 个外部用户从 quickstart → task resume 全流程跑通

当前已知状态：

| 条件 | 当前判断 | 说明 |
|------|----------|------|
| 1. 检索能力证明 | 已满足 | 当前最佳 `R@5 = 94.18%`，已达到 `94%+` |
| 2. 体验完整性证明 | 基本成立 | 主链路功能已存在，OpenSpec 已归档且 `pytest -q` 通过；仍需继续用真实 dogfooding / 外部使用确认“无断裂” |
| 3. 差异化能力采用率证明 | 未知 | 仓库内暂无足够数据支撑 `≥ 30%` 的采用率结论 |
| 4. 外部验证证明 | 未知 | 当前文档没有明确记录“至少 3 个外部用户全流程跑通” |

因此，**V1.x 还不能按这份路线图定义被视为“正式结束”**。  
更准确的状态是：**检索能力已经达标，但质量维护、采用率和外部验证仍处在阶段性收口期。**

---

## 八方评审原始文件

| 视角 | 来源 | 文件 |
|------|------|------|
| CEO/产品战略 | gstack `/plan-ceo-review` | `review-ceo-v13-v14.md` |
| 工程架构 | gstack `/plan-eng-review` | `review-eng-v13-v14.md` |
| 设计/UX | gstack `/plan-design-review` | `review-design-v13-v14.md` |
| 开发者体验 | gstack `/plan-devex-review` | `review-devex-v13-v14.md` |
| CLI 专家 | CLI design expert doc | `review-cli-v13-v14.md` |
| YC 产品六问 | gstack `/office-hours` | `review-office-hours-v13-v14.md` |
| 代码质量仪表盘 | gstack `/health` | `review-health-v13-v14.md` |
| Linus 直白审查 | `manhua:code-review-linus` | `review-linus-v13-v14.md` |
