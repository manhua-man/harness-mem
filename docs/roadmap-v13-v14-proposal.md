# harness-mem v1.3 & v1.4 路线图提案

> 基于 八 方评审综合形成（CEO/战略、Eng/工程、Design/UX、DevEx、CLI 专家、Office Hours、Health 仪表盘、Linus 代码审查）。
> 评审日期：2026-04-25 | 基线版本：v1.2.0

---

## 核心判断

**v1.3 + v1.4 = V1 体验封口层。不做 V2 大重构，不扩平台，不提前引入 cross-encoder 或 graph DB。**

当前阶段的主要矛盾已从"功能是否存在"转向"功能是否足够可靠、可解释、可维护"。v1.3 和 v1.4 应该让现有用户在每天使用中感觉到"这东西变靠谱了"。八个评审在此方向上高度一致。

> **Office Hours 的警示：** 当前 pain is real but mild。如果 Claude Code 官方内置 memory，80% 价值被吸收。Moat 是 local-first privacy + multi-client + 可审计性，但这些都很 thin。生存策略是拼 integration breadth + data ownership，而非跟官方卷 feature 密度。现阶段不建议过早考虑商业化。

---

## v1.3 范围（建议 2-3 周）

### P0: Purge 命令（Compact Guard 闭环）

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

| 来源 | 优先级 |
|------|--------|
| CEO: P1（基础设施升级）| Eng: Medium, 2-3d | Benchmark: R@5 87.3% → 目标 94%+ |

**用户痛点：** 同义词、语义变换场景搜不到。multi-session R@5 仅 79.2%，temporal-reasoning 仅 82.8%。

**实现方案（Eng 评审细化）：**
1. `storage/vector_index.py` — `HarnessVectorIndex` 类
   - 模型：`sentence-transformers/all-MiniLM-L6-v2`（384 维，~100MB）
   - lazy load：仅在 hybrid search 时加载，不在 ingest 时阻塞
   - 向量存储：numpy 文件 + JSON 索引，不引入外部向量 DB
2. `storage/hybrid_search.py` — 编排层
   - 不修改现有 `SQLiteIndex.search()`
   - 默认权重：FTS 0.4、向量 0.6（benchmark 调优后固化）
   - fallback：无 sentence-transformers 时自动退化为纯 FTS
3. 接口：`VerbatimStore.search()` 增加 `mode="auto"` 参数

**不做的：**
- ❌ ReRanker（cross-encoder）— V2 再做，推理成本高
- ❌ ChromaDB — 违反 local-first 原则
- ❌ semantic chunk — V2 再做

**验证：** LongMemEval R@5 ≥ 94%

---

### P1: CLI 体验微调（渐进披露收口）

| 来源 | 优先级 |
|------|--------|
| CEO: P2 | Design: 多个问题 | CLI Expert: 3 个 P0、5 个 P1-P2 | DevEx: P2 |

**改动清单（低风险、高感知）：**

**P0（来自 CLI Expert 评审）：**

| 问题 | 改动 | 位置 |
|------|------|------|
| `timeline --help` 不显示默认 50 | 把 `default=50` 加到 argparse 参数中 | `cli.py` |
| `search` 无 query 时抛 argparse error | 捕获 `SystemExit` 后输出友好提示 + 列出最近 observation 标题 | `cli.py` |
| `correct`/`handoff` 的 `--help` 不提示交互式 | help 文本标注"（交互式：参数可省略，终端中逐个提示）" | `cli.py` |

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

| 来源 | 优先级 |
|------|--------|
| DevEx: P0-P2 | Health: 22 lint/26 type errors | Linus: 多处静默异常 |

**Health 仪表盘当前基线（详见 `review-health-v13-v14.md`）：**
- 43/43 测试通过，3.73s 跑完
- 22 个 lint 错误（20 个可用 `ruff --fix` 自动修）
- 26 个 type 错误（主流模式：`list?[T]` 返回类型未做 None guard）
- 覆盖率 77%（最低：`cli_commands.py` 52%、`mcp/server.py` 66%）
- 0 个 TODO/FIXME（干净）

**改动清单：**
- 跑 `ruff --fix` 清理 20 个自动可修复 lint 错误
- 修复 `list?[T]` → `Optional[list[T]]`（修复 12/26 个 mypy 错误）
- 清理 6 个冗余 `Optional` import（Pydantic v2 不再需要）
- Adapter 静默吞异常改为 logging（Linus: "去你的"——`except Exception: pass`）
- `list_project_sessions` 用 `read_text()` 加载整个文件计数行 → 改为 `readline()` 流式（50MB 文件会爆内存）
- Storage layer 单元测试（`sqlite_index.py` 独立测试）
- Adapter 文件不存在时 warning 而非静默空返回
- MCP server smoke test 提升覆盖率
- SQLite 错误包装为用户友好消息（全局异常钩子）

---

## v1.4 范围（建议 2-3 周）

### P0: Provenance 追溯

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

| 来源 | 优先级 |
|------|--------|
| DevEx: P1 | Eng: 隐含 | Design: 提到交互式模式提取 |

**当前问题：** `cli.py` 1242 行，新增 adapter 需改 3+ 文件。

**实现：**
- `cli.py` 按子命令拆分为 `commands/` 包（`commands/ingest.py`、`commands/doctor.py`...）
- 交互式模式提取为 `_interactive_*()` 独立函数
- 新增 `BaseAdapter` 基类或 Protocol，统一 adapter 契约

---

### P2: 记忆质量评分

| 来源 | 优先级 |
|------|--------|
| CEO: P2 | 其余: 未提及 |

- structured entries 增加 last-accessed + usage count
- `doctor` 展示低质量 / 陈旧 entries 数量
- 自动清理建议

---

## v1.3 / v1.4 不做的（明确推迟到 V2 / 不承诺）

| 功能 | 理由 | 目标版本 |
|------|------|---------|
| ReRanker（cross-encoder） | ~500MB 模型，推理成本高，在 hybrid R@5 ≥ 94% 后评估 | V2 |
| Graph 记忆（实体关系图） | 复杂度高，V1 用户无此需求信号 | V2 |
| 跨客户端任务续接 | 需协议设计，当前 Claude Code + Codex 各自独立已够用 | V2 |
| Cursor / Gemini adapter | 核心用户在 Claude Code + Codex，扩平台是增长不是留存 | v1.5（保持原计划） |
| Web UI / Dashboard | 不确定用户是否真的需要 web 界面，CLI 是正确的最小交付 | V2+ 观察 |
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

4 条全满足后才启动 V2（graph、跨客户端续接、ReRanker）。

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
