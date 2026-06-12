# Roadmap: harness-mem v3.4

> 状态：已发布，当前版本 3.4.4。
>
> 主题：Runtime Health, Cost Discipline, and Regression Gates。让 memory runtime
> 能看见自己的 job health、MCP surface 成本、上下文浪费、版本漂移和跨版本质量变化；
> v3.2 已提供的基础 generated freshness / compile metrics 在这里被汇总，不重复作为首要实现。

---

## 目标

v3.4 的目标不是新增更多记忆类型，也不是做完整 dashboard 产品；
它负责把 v3.1 dream ledger、v3.2 generated metrics、v3.3 temporal query traces 和 runtime event log
收成一套可诊断的 runtime health、cost discipline 和 regression gates。

```text
wake/search/distill/file_context/dream/wiki
-> tool-call / output-token / latency signals
-> cost observer
-> health report / doctor hints
-> benchmark regression gates
```

参考线：

- `codedb-mcp`：Codex transcript observer、high-output calls、missed bundle/context opportunities、token/runtime benchmark。
- `claude-mem`：queue health、worker health、graceful degradation。
- `EverOS`：benchmark / use-case 分层。
- `evo`：runtime ledger、strategy events、version drift visibility。

## 边界

- 不采集用户内容到云端。
- 不把 observability 做成默认后台 daemon。
- 不因 cost observer 失败阻断 wake/search/distill。
- 不把 cost 当作 observability 子项；token budget、high-output detection、truncation metadata 单独成类。
- 不用单一 LongMemEval 分数替代用户可见质量。
- 不把 dashboard 做成主产品 UI；先做 doctor/status/report。
- 不重新实现 v3.2 的 source-map freshness；这里只汇总已有 generated-layer metrics。

## v3.4.0：MCP Surface Cost Observer

> 状态：已发布，当前版本 3.4.0。

**用户故事**：维护者能知道哪些 MCP / Slash surface 正在浪费上下文。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | local transcript observer | 已完成：MCP `tools/call` 成功返回后 best-effort 写入本地 `events.log` 的 `mcp_surface_cost` 元数据事件 |
| P0 | token estimate | 已完成：估算 wake/search/distill/file_context/dream/wiki-like compact 输出 token，并记录 tokenizer path |
| P0 | high-output detection | 已完成：按 surface 默认阈值标出宽泛 search、过大 wake、过大 distill packet 等高输出调用 |
| P1 | missed-opportunity hints | 已完成：提示可改用 timeline drilldown、compact context、source drilldown、narrower query 或更小 distill packet |

### 当前实现（2026-06-08）

- `harness_mem.runtime_cost` 负责纯本地 cost analysis、`events.log` 写入和聚合报告。
- MCP server 在 `tools/call` handler 成功返回后调用 observer；observer 异常只写 stderr log，不改变 tool result。
- 新增 MCP `surface_cost_report`，按 project / days / limit 聚合 recent surface cost。
- 事件只保存 surface、tool name、duration、输出 token / char 计数、argument shape、result shape 和提示类型；
  不保存 raw query、raw path、原始 transcript 或 response content。

## v3.4.1：Runtime Health Report

> 状态：已发布。

**用户故事**：`/hm:status` / doctor 能显示 memory runtime 的健康，而不是只显示安装是否成功。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | queue/job health | dream/reflection/metabolism job 的 last run、failures、retryable 状态可见 |
| P0 | generated cache rollup | 汇总 v3.2 wiki / claim / source map freshness，不重新定义 generated compiler |
| P0 | retrieval health | wake/search latency、result count、truncation frequency |
| P1 | graceful degradation report | 失败时解释降级路径，不阻断主任务 |

### 当前实现（2026-06-08）

- `harness_mem.runtime_health.runtime_health_report` 汇总 reflection / dream / metabolism
  job last run、failures、retryable 状态。
- `health_summary`、doctor、`/hm:status` 背后的 MCP `get_project_status` 均暴露 runtime health。
- generated cache rollup 复用 v3.2 `knowledge_cache_health`，不重新定义 compiler。
- retrieval health 由本地 `mcp_surface_cost` 事件汇总 wake/search/file_context/timeline/
  temporal_query 的 latency、result count 和 truncation/high-output frequency。
- 每个切片失败都会落到 `graceful_degradation.warnings`，不阻断 wake/search 主链。

## v3.4.2：Benchmark Matrix and Regression Gates

> 状态：已发布。

**用户故事**：改 memory runtime 时，能看出哪类能力退化，而不是只看总分。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | benchmark taxonomy | use cases / methods / datasets / dimensions 分层 |
| P0 | per-surface regression | wake、search、file_context、wiki compact、temporal query 分别有 smoke / regression |
| P0 | dimension score | LongMemEval 按 knowledge-update、temporal-reasoning、multi-session 等维度报告 |
| P1 | release snapshot | 每次 release 可生成简短 benchmark snapshot |

### 当前实现（2026-06-08）

- 新增 `harness_mem.benchmark_matrix.benchmark_matrix_report`，按 use cases / methods /
  datasets / dimensions 输出 taxonomy。
- MCP `benchmark_matrix_report` 暴露 wake、search、file_context、wiki compact、
  temporal query 的 per-surface smoke/regression coverage。
- LongMemEval 五个维度以 dimension row 形式进入报告，避免用单一总分替代分维度质量。
- release snapshot 读取 `benchmark-suite/artifacts/*/run_manifest.json`，报告最新 artifact、
  accepted/failed run 计数和 gate 状态。
- 当前 artifact set 有 7 个 validated runs；`benchmark_matrix_report` 可从
  `results/*.json` 或 tracked `release-snapshot.json` 推断 accepted 状态，报告
  7 accepted、0 failed、0 unknown，当前 benchmark gate passed。
- `benchmark_matrix_report()["claim_readiness"]` 额外暴露 public-claim gate：当前
  token/cost saving 与 true vector-hybrid latency 都是 `ready=false`，防止把
  accepted artifact 误读成 token 节省或 true hybrid 性能证明。

## v3.4.3：Version and Install Drift Visibility

> 状态：已发布。

**用户故事**：多 host plugin / skill / CLI 组合出现漂移时，doctor 能尽早发现。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | wire-format version | plugin / skill / MCP / CLI 暴露兼容版本 |
| P0 | doctor drift check | host plugin 与 runtime 版本不匹配时提示风险和修复路径 |
| P0 | no silent stale install | `/hm:status` 能显示 stale registration 或旧 slash command |
| P1 | install/update guidance | 给出 host-specific 更新建议，但不擅自改全局配置 |

### 当前实现（2026-06-08）

- 新增 `harness_mem.version`，CLI/MCP/plugin/skill 共用 `hm-wire-v3.4` wire-format 常量。
- MCP `initialize.serverInfo`、`get_project_status.runtime_versions` 和 doctor/status 输出
  runtime + wire-format 版本。
- `harness_mem.version_drift.version_drift_report` 检查 repo-local plugin manifest、
  skill、`/hm:status` slash asset 是否 stale，并给出 host-specific 更新建议。
- plugin manifest、skill frontmatter、`/hm:status` frontmatter 均声明 `hm-wire-v3.4`；
  报告只提示，不擅自改全局 host config。

## v3.4.4：Cost Budget Policy

> 状态：已发布。

**用户故事**：系统有可解释的 token budget 策略，并能指出哪些调用违反了预算纪律。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | per-surface budget | wake/search/file_context/wiki/dream 默认预算可配置 |
| P0 | truncation metadata | 输出包含 truncated-by、remaining-drilldown、source ids |
| P0 | status summary | status 显示最近高成本调用和建议 |
| P1 | policy versioning | budget policy 有版本，便于 dream/observer/report 引用 |

### 当前实现（2026-06-08）

- `harness_mem.runtime_cost` 引入 `cost-budget-v3.4.4` policy version 和
  wake/search/file_context/wiki/dream/distill 默认 per-surface budget。
- `.harness-mem.toml` 支持 `cost_budget.*_tokens` typed config，预算仍是 advisory-only，
  不让 observer 自动改写输出。
- cost event 记录 `budget_tokens`、`budget_exceeded`、`truncation.truncated_by`、
  `remaining_drilldown` 和 privacy-preserving `source_id_count/source_ids`。
- MCP `surface_cost_report`、`get_project_status.cost_budget` 和 CLI status 显示最近高成本
  调用、top opportunities 与 drilldown 建议。

## 后置项

这些功能有价值，但不是 v3.4 必要门槛：

| 项目 | 原因 |
|---|---|
| Web dashboard | doctor/status/report 先够用；dashboard 容易把产品重心带偏。 |
| 全量 benchmark matrix | 先覆盖核心 surface 和 LongMemEval 维度；完整矩阵可随 release train 增长。 |
| 自动调 budget | 先报告和建议，不让 observer 自治改运行策略。 |

---

## Release Gate

- `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy harness_mem`
- Focused tests:
  - local observer does not mutate transcripts
  - high-output detection
  - queue / generated cache / retrieval health
  - version drift warning
  - per-surface budget enforcement
  - benchmark dimension snapshot

---

## 一句话

v3.4 是 memory runtime 的健康、成本与回归纪律：本地观察、可解释预算、版本漂移检测、分维度 benchmark，让系统知道自己什么时候拖慢主链、浪费上下文或质量退化，但不把 dashboard 或自动调参做成必要功能。
