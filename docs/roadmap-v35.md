# Roadmap: harness-mem v3.5

> 状态：已完成。
>
> 主题：Benchmark Evidence and Public Claim Readiness。把 benchmark 从
> "pass/fail 验收"升级成可复现、可解释、可对外引用的 evidence layer。

---

## 目标

v3.5 不新增记忆类型，也不改变 wake/search/truth 主链。它负责把现有
`benchmark-suite`、`benchmark_matrix_report`、release snapshot 和 public-claim gate
收成一套可以回答这些问题的证据系统：

```text
BENCH task
-> reproducible runner / manifest
-> metrics + accepted/partial/failed classification
-> RESULTS.md / release snapshot
-> public-claim readiness
```

参考线：

- `MemPalace`：benchmark 文档直接列数据集、指标、样本数、复现命令和限制。
- `codedb-mcp`：token/runtime 对照必须有 enabled vs disabled artifact。
- `hypatia`：embedding / retrieval benchmark 要区分模型、数据集和指标。
- `OpenSpace`：skill / token benchmark 叙事要能解释质量边界，而不是只给通过状态。

## 边界

- 不把 `pytest pass` 当 benchmark 结果。
- 不把旧 smoke、429、partial attempt artifact 混进 accepted release snapshot。
- 不对外宣称 token/cost saving 或 true vector-hybrid latency，除非 claim gate 为 ready。
- 不采集云端 telemetry，不保存 raw user content。
- 不用单一 LongMemEval 总分替代所有用户可见质量。
- 不让 benchmark runner 静默修正 product behavior。

## v3.5.0：Artifact Hygiene and Taxonomy

**用户故事**：维护者能一眼分清哪些 artifact 是 accepted evidence，哪些只是早期尝试或失败样本。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | artifact state taxonomy | 定义 `accepted` / `partial` / `failed` / `quarantined`，并在 manifest 中强制记录 |
| P0 | stale artifact cleanup | 早期 smoke / 429 / partial 尝试从 release snapshot 输入中排除 |
| P0 | BENCH purpose map | 每个 BENCH 记录类型、目的、影响面和不能证明什么 |
| P1 | reproducibility notes | 每个 runner 写清输入、依赖、环境变量和可复现命令 |

**实现说明**：`benchmark_matrix_report()` 现在返回 `taxonomy.artifact_states`
（`accepted` / `partial` / `failed` / `quarantined`）、`taxonomy.purpose_map`、
release snapshot counts，以及每个 public claim 的 machine-readable gate。

## v3.5.1：Results Report

**用户故事**：用户不用读一堆 JSON，也能看懂 benchmark 测了什么、结果如何、影响什么。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `benchmark-suite/RESULTS.md` | 按 BENCH 输出 metrics、样本量、状态、限制和解释 |
| P0 | metric vs gate separation | `pass` 只表示验收通过；latency/token/recall/failure rate 才是 benchmark 数据 |
| P0 | latest release snapshot | status/report 能指向最新 accepted run 和 gate summary |
| P1 | human-readable canvas | 产出适合人工审阅的分类表或图示，而不是只给机器 JSON |

**实现说明**：`benchmark-suite/RESULTS.md` 与 `release-snapshot.json` 共同承担
human-readable summary 与 clean-checkout snapshot；package resource fallback 与 repo
source 保持 byte-equivalent truth test。

## v3.5.2：Public Claim Readiness

**用户故事**：对外文案只能说已经有 artifact 支撑的 claim。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | claim gate schema | 为 token/cost saving、true hybrid latency、retrieval recall 等 public claims 定义 ready 条件 |
| P0 | `benchmark_matrix_report` rollup | report 明确列出 ready=false 的 claim 和缺口 |
| P0 | docs guard | README / reference docs 不得把 ready=false 的指标写成已证明 |
| P1 | failure-mode notes | 记录 false pass、zero delta、synthetic-only latency 等弱信号原因 |

**实现说明**：`claim_readiness` 覆盖 token/cost saving、true vector-hybrid latency
和 retrieval recall。当前三个 gate 仍为 `ready=false`，README/reference docs 不能把
这些指标写成已证明。

## v3.5.3：Benchmark Runbook Hardening

**用户故事**：下一次 release 前，维护者能按 runbook 重跑 benchmark 并解释差异。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | runbook order | 明确先清理、再跑、再 validate、再 render report |
| P0 | delta diagnosis | delta=0、样本太少、fallback 过多时给出诊断而不是假装无退化 |
| P1 | release checklist | release gate 明确哪些 benchmark 是 required，哪些是 advisory |

**实现说明**：`validate_release_snapshot.py` 校验 release snapshot v2、claim gates
和 retrieval shootout summary；`render_report.py` 会为 latency、client-pair 和
true-hybrid retrieval 产出对应 report，而不是把不同 benchmark 强套成同一表。

## 一句话

v3.5 把 benchmark 做成证据账本：每个 BENCH 都说明测什么、为什么测、结果多少、
限制在哪；没有 artifact 的对外 claim 继续保持不可发布。
