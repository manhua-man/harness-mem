# Roadmap: harness-mem v1.6.x

> 状态：v1.6.0 - v1.6.2 已完成实现；完整当前状态见 [`roadmap-status.md`](./roadmap-status.md)。本文件保留切片设计、验收口径和历史决策链。
>
> 配合 [`roadmap-v15x.md`](./roadmap-v15x.md) 与 [`roadmap-vision-v16-v18.md`](./roadmap-vision-v16-v18.md) 阅读：v1.5.x 是把当前架构做扎实，v1.6.x 是把 vision 文档里 v1.6 那段"持久化向量 + 记忆分型 + 预算纪律 + distill 安全"翻译成可执行的三切片。
>
> 每条任务的验收都以源码、基线数字或现有 benchmark 为锚，不写无 baseline 的承诺。
>
> 三个版本的用户视角故事线：
> - **v1.6.0** — 我能看到 R@5 在 5 个维度上各自是多少；`MemoryEntry` 现在有 `memory_type`，但 wake-up 行为不变
> - **v1.6.1** — wake-up 不再让 episodic 噪声淹没 semantic 规则；distill 即使想改 truth 也改不动
> - **v1.6.2** — 查询不再热路径 encode；P95 latency 下降一档；可以选更新的 embedding 模型

---

## 切片之间的依赖向前推

| 切片 | 价值 | 为什么必须先做它 |
|------|------|------------------|
| v1.6.0 | 给 R@5 加上 5 个维度切片，给 schema 加 `memory_type` 字段 | 否则 v1.6.1 / v1.6.2 的"质量提升 / 分桶预算改善"无从验证 |
| v1.6.1 | wake-up 分桶预算 + distill 只读边界 | 在 v1.6.2 引入更强 embedding 之前，先把"输出可控、写边界锁死"做掉，避免 v1.6.2 把更多噪声塞进 wake |
| v1.6.2 | sqlite-vec 持久化向量 + embedding 模型评估 | 只有 v1.6.0 的 5 维报告 + v1.6.1 的预算纪律到位后，模型升级的收益才能被识别和归因 |

每个切片都可以独立发版、独立回滚。

---

## 已决策（v1.6.0 启动前定齐）

vision 文档中留白的 3 个品味决策，本 roadmap 启动前一次定齐，避免 v1.6.1 / v1.6.2 启动时再陷入循环讨论。

### 决策 1：sqlite-vec 必选（v1.6.2）

**结论**：v1.6.2 起 `pip install "harness-mem[hybrid]"` 强制带 sqlite-vec，不再保留 optional 路径。

**理由**：sqlite-vec 是 C 库 + SQLite 扩展（`.so` / `.dll` 单文件），不引入服务端依赖、不违反 local-first。保留 optional 反而会让 `hybrid` 默认路径在缺扩展时降级到 FTS——而 v1.6.2 的产品定位就是"hybrid 应该是 default"。把它做成可降级会模糊定位、扩大测试矩阵、产生"为什么我的 hybrid 不工作"类支持成本。

**例外**：如果用户系统不支持加载 sqlite extension（极少数 hardened SQLite 构建），`harness-mem doctor` 给出明确错误码与降级到 v1.5.x FTS-only 行为的指引；但这不是默认路径。

### 决策 2：默认 type bucket 比例 = 50 / 50 / 0（v1.6.1）

**结论**：v1.6.1 起 `[wake]` 默认配额 `bucket_quota_semantic = 0.5`、`bucket_quota_episodic = 0.5`、`bucket_quota_procedural = 0.0`。

**理由**：

- 当前 wake-up 输出最容易被淹没的是 confirmed rule / relation fact（即 semantic 桶），把它从"全库混排"提到"至少占 50%"是最直接的体验提升
- procedural 在 v1.8 真正 populate 之前 quota 为 0，避免空桶占预算
- 50 / 50 是最对称、最不偏 episodic 也不偏 semantic 的起点；任何后续调整必须用 v1.6.0 的五维 R@5 作为锚点重新评估

**配置可覆盖**：用户可在 `~/.harness-mem/config.toml` 的 `[wake]` 段重写比例；总和必须 = 1.0，否则 `harness-mem doctor` 报 `HM-1xx` 配置错误码（具体码号由 v1.6.1 设计时分配）。

### 决策 3：embedding 模型由 shootout 决定，不在启动前预选（v1.6.2）

**结论**：v1.6.2 启动后第一周内必须跑完 shootout 并 commit `docs/benchmark/v162-embedding-shootout.md`；shootout 决策规则一次定齐：

| 候选模型 | 体积 | 维度 | 许可 |
|----------|------|------|------|
| `all-MiniLM-L6-v2` | 22MB | 384 | Apache 2.0 |
| `bge-small-en-v1.5` | ~130MB | 384 | MIT |
| `nomic-embed-text-v1.5` | ~130MB | 768 | Apache 2.0 |

**决策规则（按顺序匹配第一条命中即停）**：

1. 若三者中存在某个候选在 v1.6.0 baseline 的 5 个维度上**全部**不回退（≤ baseline + 0 pp 容错），且**至少 2 个维度** ≥ +1 pp，选它；多个候选满足时取**总 R@5 最高**的
2. 若没有候选满足规则 1，但存在候选**至少 4 个维度不回退**且**至少 1 个维度** ≥ +2 pp，选它
3. 若两条都不满足，**保持 `all-MiniLM-L6-v2` 不变**（v1.6.2 仍交付 sqlite-vec 持久化，模型升级延后到 v1.6.3 / v1.7）

**为什么不在启动前预选**：在没有 v1.6.0 baseline 的情况下预选模型，等于用直觉决策；用规则 + 数据决策，避免陷入"哪个模型更好"的反复讨论。

**默认候选优先级（仅当 shootout 数据全等时作为 tiebreaker）**：`bge-small-en-v1.5` > `nomic-embed-text-v1.5` > `all-MiniLM-L6-v2`，按"对当前主要用户场景（中英混排代码语境）的预期 fit"排序。

---

## v1.6.0：Measurement foundation + memory typing

**用户故事**：跑完 LongMemEval 直接看到五个维度（multi-session / temporal-reasoning / single-session-* / knowledge-update / abstention-style）各自的 R@5；`MemoryEntry` 现在有显式 `memory_type` 字段，但 wake-up 行为完全不变（"非破坏性 baseline"）。

**前置基线（v1.6.0 启动当日跑一次，写入 `docs/benchmark/v160-baseline.md`）**：
- LongMemEval 全量 + per-type，三种 mode（fts / hybrid / hybrid-stemfallback）各跑一遍 R@5
- 当前 `harness_mem.tools.longmemeval` 输出的 `per_type` 数值（已存在但未作为 KPI 报告）
- v1.5.3 已发布的 hybrid 全量 P95 latency

| 优先级 | 任务 | 验收 |
|--------|------|------|
| P0 | LongMemEval 五维报告**正式入档**：把现有 `per_type` 输出晋升为一等公民——`results_*.json` 必须含 `per_type` 字典；CLI 输出按维度对齐打印；新增 `docs/benchmark/longmemeval-five-dimensions.md` 解释每个维度含义和当前 baseline | `python -m harness_mem.tools.longmemeval ...` 输出含 `PER-TYPE RECALL` 段；JSON 含 `per_type`；五维表格写入 `docs/benchmark/v160-baseline.md` |
| P0 | `MemoryEntry.memory_type` 字段：新增 `memory_type: Literal["episodic", "semantic", "procedural"]`，默认 `semantic`；`from_dict` 兼容老数据（缺失时按 `category` 自动派生：`bug / decision -> semantic`，`architecture / convention / api -> semantic`，无对应规则的 catch-all -> `episodic`）；`procedural` 字面量保留但 v1.6.0 不会被产生 | `tests/storage/` 中加测；老数据加载零回归；`memory_type` 出现在 `to_dict / from_dict / __init__.py` 导出 |
| P0 | 派生规则一次性 backfill：写一个**幂等**的 `harness-mem maintenance assign-memory-types --dry-run / --apply`，把现有所有 `MemoryEntry` 写入 `memory_type`；不修改 wake-up / search / MCP 任何行为 | dry-run 默认；apply 写完后再次 dry-run 显示 0 条待变更；命令行测试覆盖 |
| P1 | 让 `MemoryEntry.memory_type` 在 `search_memory` / `/search` 返回 payload 里**只读暴露**（不接受 filter 参数）；MCP `search_memory` 的 result 增加 `memory_type` 字段 | MCP / REST / CLI 三端测试断言新字段存在；不存在 filter 行为变更 |
| P1 | LongMemEval 维度归一化：当前 dataset 字符串实测含 `multi-session / temporal-reasoning / single-session-user / single-session-preference / single-session-assistant / knowledge-update`——把这 6 个登记成 `LONGMEMEVAL_QUESTION_TYPES` 常量，新维度命中触发 warning 而不是静默吞掉 | 单测覆盖：未知维度产生 warning；已登记维度归类正确 |
| P2 | benchmark CI 切片：`pytest tests/benchmark/` 跑通；不在 main 测试套件里阻塞 PR，但要可单独运行 | `python -m pytest tests/benchmark -q` 全绿 |

**不列入此版本（防止 scope creep）**：
- wake-up 按 `memory_type` 分桶——挪到 v1.6.1
- distill 安全边界——挪到 v1.6.1
- `procedural` 类型的实际生成路径——挪到 v1.8（vision 文档已经划清边界）
- 持久化向量索引——挪到 v1.6.2
- embedding 模型升级——挪到 v1.6.2
- search 按 `memory_type` filter——v1.6.0 只**暴露**字段，不**消费**字段；filter 是行为变化，留给 v1.6.1 与分桶预算一起做

**为什么先把"测量"做了再做"行动"**：v1.5.2 在没有 per-type 报告的情况下，差点把 `fusion_sort_error` 方向的 RRF 调权当成主线优化路径，最后是诊断脚本告诉我们真正的瓶颈在 FTS 召回。v1.6.x 不能再犯同样的错——任何对 retrieval / wake-up 的优化，必须能在五维上看到分桶移动，否则就是噪声调参。

---

## v1.6.1：Wake-up bucket budget + distill 只读安全边界

> **状态：2026-05-19 已完成。** 详见 [`openspec/changes/archive/2026-05-24-2026-05-19-v161-bucket-budget-and-distill-readonly/`](../openspec/changes/archive/2026-05-24-2026-05-19-v161-bucket-budget-and-distill-readonly/)、`CHANGELOG.md` `[1.6.1]` 段，与 [`docs/benchmark/v161-bucket-budget-impact.md`](./benchmark/v161-bucket-budget-impact.md)。

**用户故事**：wake-up 输出不再被一堆 episodic observation 抢光预算把 confirmed rule 挤出去；distill 阶段即使 LLM 想改 truth 也改不动——所有写动作只能落到候选层，不能直接 mutate `ConfirmedRule / RelationFact / Observation`。

**前置基线**：
- 沿用 v1.6.0 的五维 baseline；本切片要求**至少 4 个维度不回退**（允许 ≤ 1 维度小幅波动 ≤ 2 pp，避免分桶预算把某一维度优化但牺牲另一维度）
- 当前 wake-up 输出 token 分布的快照（按 category 统计 entries 数量、占用 token）

| 优先级 | 任务 | 验收 |
|--------|------|------|
| P0 | wake-up 分桶预算：`[wake]` config 增加 `bucket_quota_semantic / bucket_quota_episodic / bucket_quota_procedural`，**默认 50 / 50 / 0**（已决策，见下方"已决策"段）；总 token 上限不变；超出某一桶配额时 ranker 在该桶内截断，不挤占其他桶 | wake-up 测试覆盖三种典型分布；输出 header 显示当前配额比例与实际填充率 |
| P0 | distill 只读边界：定义 `DistillContext` 接口，仅暴露 `read_observations / search / compare / suggest_*` 类方法；禁止从 distill 路径调用任何 `ConfirmedRuleStore.delete / .update` 或 `RelationFact.delete / .update`；试图绕过的 case 在测试层被静态断言抓住 | 新增 `tests/distill/test_readonly_boundary.py`，覆盖：直接调用被禁方法 raises；`suggest_*` 路径只写候选层 |
| P0 | distill 写动作降级为候选：所有 distill 输出走 `RuleCandidate / MergeSuggestion / ConflictCandidate / SupersedeCandidate`（v1.6.1 至少先有 RuleCandidate / MergeSuggestion 两类；其它 placeholder） | distill 单测覆盖：每条建议都有可审核字段（reviewer_id / confirmed_at / rejected_at） |
| P1 | wake-up bucket 显式可关：`harness-mem wake --no-bucket-quota` 与 config `bucket_quota_enabled = false` 把 v1.6.1 行为退回 v1.6.0（全库混排 top-k） | flag / config 测试均覆盖；关闭后输出与 v1.6.0 等价 |
| P1 | search 按 `memory_type` filter：MCP / REST / CLI 增加 `memory_type=episodic|semantic|procedural` 可选参数（v1.6.0 只暴露字段，v1.6.1 才允许过滤） | 三端测试覆盖；默认行为不变 |
| P2 | wake-up 输出对 bucket 截断标注（`[truncated within bucket: episodic 3/8]`），延续 v1.5.1 截断显式标注的精神 | wake 单测覆盖三种截断场景 |

**不列入此版本**：
- bi-temporal 字段（`valid_from / valid_to / supersedes`）—— vision 文档已划归 v1.7
- 自治删 truth —— vision 与 dream-absorption 文档都明确不做
- 持久化向量索引 —— v1.6.2
- 跨项目 bucket 共享配额 —— 没有用户场景

**为什么 distill 安全边界要在 v1.6.1 提前做**：vision 文档里这条原本可以推到 v1.7 / v1.8，但一旦 v1.6.2 引入持久化向量后 distill 能"读全库 + 跑聚类"，写边界没锁死就会被诱惑去"顺手清理一下"。**安全边界必须先于能力增强落地**。

---

## v1.6.2：sqlite-vec 持久化向量 + embedding 模型评估

**用户故事**：每次 `wake-up` / `search` 不再热路径 encode 整个 FTS 候选池；P95 latency 下降一档；用户可以选 bge-small / nomic-embed 替代 all-MiniLM-L6-v2，不需要等 v2.0。

> **状态：2026-05-20 runtime complete；manual benchmark gates remain.** 代码、测试与收尾文档已落地；`docs/benchmark/v162-embedding-shootout.md` 已按规则 3 保持 `all-MiniLM-L6-v2`。完整 LongMemEval final run 与 P95 latency 仍是发版前手动门槛，不在 CHANGELOG 中冒充已验证。

**前置基线**：
- v1.6.0 + v1.6.1 已落地的五维 R@5
- 当前 v1.5.3 实测 hybrid P95 latency `625.17ms`（含 vector encode）
- v1.6.0 的 `python -m harness_mem.tools.longmemeval --mode hybrid` 全量耗时

| 优先级 | 任务 | 验收 |
|--------|------|------|
| P0 | sqlite-vec 集成（**必选**，见下方"已决策"段）：`pip install "harness-mem[hybrid]"` 强制带 sqlite-vec；`verbatim_index.sqlite` / `structured_index.sqlite` 增加 `vec_*` 表，存 384/768 维向量；ingest / save 时落盘 embedding | 已完成；单测覆盖写入即查，二次启动直接读已有 vector，不再 encode |
| P0 | search 走持久化向量 JOIN：`HybridSearchLayer._search_hybrid` 改为 SQL JOIN 路径，候选池查询不再调 `model.encode`；query 端 embedding 仍然实时算（只 1 次） | 已完成；缺表、空表、全过滤时回退 FTS；P95 latency 的完整手动验证仍保留为 benchmark 门 |
| P0 | embedding 模型评估并拍板：在 v1.6.0 的五维 baseline 上分别跑 `all-MiniLM-L6-v2 / bge-small-en-v1.5 / nomic-embed-text-v1.5`，写 `docs/benchmark/v162-embedding-shootout.md`；按 `recall_per_dim_uplift / model_size / cold_load_time` 三轴决策；最终默认模型必须**至少在 3 个维度不回退**且总 R@5 不低于 v1.6.1 baseline | 已完成；报告触发规则 3，默认模型保持 `all-MiniLM-L6-v2` |
| P1 | 向量层 schema 升级路径：现有用户 `.harness-mem/data/` 第一次升级到 v1.6.2 时，`harness-mem doctor` 输出"需要重建向量索引"提示 + 一键命令 `harness-mem maintenance rebuild-vector-index --project <name>`；不阻塞 search（缺向量时回退 FTS） | 已完成；doctor / rebuild / fallback 测试覆盖 |
| P1 | embedding 模型版本写入 schema：每条 `vec_*` 行带 `model_id / model_version`，不同模型混存时按版本筛选，避免老索引污染新模型查询 | 已完成；换模型后老向量会被自动过滤或回退 |
| P2 | LongMemEval 五维 R@5 目标：单一维度 ≥ +1 pp（不强求总 R@5 跨过 0.96，留给 v1.7 时间维度优化） | benchmark 报告含 v1.6.0 / v1.6.1 / v1.6.2 三列对比 |

**不列入此版本**：
- bi-temporal —— v1.7
- procedural memory schema —— v1.8
- bge-large / 1.3GB 级别模型 —— vision 文档明确划线"local-first 体积上限在 small/base"
- 远程 embedding API（OpenAI / Cohere）—— 违反 local-first

---

## 与上游 vision 文档的关系

| vision 文档条目（`roadmap-vision-v16-v18.md`） | 在 v1.6.x 的落点 |
|---|---|
| 持久化向量索引（sqlite-vec） | v1.6.2 P0 |
| 记忆三层分型 | v1.6.0 P0（schema）+ v1.6.1 P0（消费） |
| 分桶预算纪律 | v1.6.1 P0 |
| Distill 只读安全护栏 | v1.6.1 P0 |
| Embedding 模型升级 | v1.6.2 P0 |
| LongMemEval 五维细分 | v1.6.0 P0 |

vision 文档里"v1.6 待确定的品味决策"四条：
- 默认 embedding 模型 → **已决策**：v1.6.2 启动后 1 周内跑 shootout，按规则匹配；规则 3 触发时保持 all-MiniLM-L6-v2 不变（详见上文"已决策 3"）
- sqlite-vec 必选 / optional → **已决策**：必选（详见上文"已决策 1"）
- 一次切到三层还是两层 → **已决策**：v1.6.0 schema 上一次切到三层；`procedural` 在 v1.6.0/v1.6.1 quota 为 0 不被产生；v1.8 才真正 populate
- 分桶比例默认 → **已决策**：50 / 50 / 0（详见上文"已决策 2"）

---

## 风险与不做的事

1. **v1.6.0 不能动 wake-up / search 行为**——只加字段、加报告。任何"顺手优化"必须挪到 v1.6.1 / v1.6.2，否则失去隔离实验能力
2. **v1.6.2 的 P95 latency 下降目标必须基于真实 baseline，不是估算**——v1.5.3 baseline 是 `625.17ms`，目标 `437ms`；如果 baseline 当时跑环境与 v1.6.2 不一致，先重新跑 baseline，再设目标
3. **sqlite-vec schema 升级必须不阻塞老用户**——缺向量列时 fallback FTS，doctor 给一键 rebuild 提示；不能让用户升级后突然 search 报错
4. **不引入 KAIROS / Proactive / 自治删记忆**——继续遵守 vision 文档与 dream-absorption 文档的边界
5. **不把 LongMemEval 单一总分当 KPI**——v1.6 起只看五维，避免重复 v1.5.2 那种"调一个数字一个月"的弯路
6. **embedding 模型升级失败的退路**：如果 shootout 显示 bge-small / nomic-embed 都没显著优势（≤ +1 pp），保持 all-MiniLM-L6-v2 不动；v1.6.2 仍交付 sqlite-vec 持久化（这是延迟收益）；不强行换模型

---

## 测试与验收口径

每个切片合并到 main 之前必须满足：

- `python -m pytest -q` 全绿
- `python -m ruff check .` 无警告
- `python -m mypy harness_mem` 无错误
- `python -m harness_mem.tools.longmemeval ... --mode hybrid` 五维表格不回退（详见各切片"前置基线"）
- 对应 OpenSpec change 走完 `openspec validate <change-name>` 并归档
