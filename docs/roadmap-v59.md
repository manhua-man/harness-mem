# Roadmap: harness-mem v5.9+ Evidence & Public Claims Train

> 状态：**规划中**（基线版本 v5.6.0；**在 v5.7 / v5.8 之后**按切片发布；与
> [`roadmap-status.md`](./roadmap-status.md) 同步维护）。
>
> 主题：**从 bounded 证据到可对外宣称的 broad token/cost 与 broad quality**。
> 产品面（时序检索、养库、MCP profile）由 v5.7–5.8 承担；本 train 只解决 **benchmark、claim gate、观测与文案边界**。

---

## 一句话

v5.9+ 是 **证据线（非 optional）**：先补齐可复现的 paired agent / E2E / shootout artifact，再按 `claim_promotion` 解锁宣称；**没有 artifact 不写 broad 句**。

```text
v5.7–v5.8  你正在做：查得对、养得起、MCP 不吵
v5.9       证据地基：bounded 文案收口 + quality profile + B21+ 设计包
v5.10      broad token/cost（B21 agent_continuation_economics）
v5.11      broad quality（B22 LongMemEval E2E + B23 agent matrix replay）
v5.12      Storage v2 / Rust speedup shootout（B24；实现已有，缺 A/B 宣称证据）
v6.0       暂定：可搬运 bundle + 显式多项目 workspace（见文末）
```

## Claim 接线表（防误解锁）

| claim_id | 数据源 collection | 当前状态 | 解锁后能说 |
|---|---|---|---|
| `cost_token_evidence` | `memory_shortcut` + `functional_token_economics` | v4.6 **passed** | bounded 长源 shortcut 省钱（MS 边界句式） |
| `token_cost_saving` | `client_enabled_vs_disabled` **仅此** | **blocked**（T1/T3 负向） | 不得从 MS / broad 自动置 ready |
| `broad_token_cost_saving` | `agent_continuation_economics`（**B21，新**） | 未接线 | v5.10 合计省钱（命名任务集） |
| `broad_memory_answer_quality` | `longmemeval_e2e_qa`（**B22，新**） | 未接线 | LongMemEval E2E 准确率（附 baseline 臂） |
| `storage_v2_scale_evidence` | scale 10k/100k/1m contract | **passed** | 规模/迁移契约；**≠** speedup |
| `storage_v2_speedup` | `storage_v2_speedup_shootout`（**B24，新**） | claim_promotion **永久 blocked** 直至 B24 | p95 / 百分比（仅 shootout checklist） |

## 为什么现在做

| 诉求 | 当前缺口 | 本 train 对应切片 |
|---|---|---|
| README 写 **全局/合计** token 节省 | 无 B21；`token_cost_saving` 与 MS 无关且 blocked | v5.9.2 → v5.10 |
| README 写 **记忆带来更好答题质量** | 只有 LongMemEval **R@5** | v5.9.1 → v5.11 |
| README 写 **Storage v2 / Rust 加速** | scale ✅；无 paired shootout | v5.12 |
| codedb 级评测纪律 | 无 `harness-mem-observe`；B21+ 未进 `BENCHMARKS.md` | v5.9.0 / v5.9.2 |

**与 v5.7 的关系**：v5.7.3 冻结 **检索** 分维表 → v5.9.1 的 quality profile gate 应相对 **v5.7.3 artifact**（未发则 v5.6，须在 release notes 写明）。v5.11 E2E 的检索臂须在 v5.7 主路径发布后 **重锚** 或标注不得写 temporal 产品收益。

## 产品原则

1. **Claim gate 先于文案**：新 `claim_id` 进 `claim_readiness` 之前，README 不出现对应句式。
2. **Bounded 不自动升 broad**：`cost_token_evidence.passed` ≠ `broad_token_cost_saving`；MS 不得写进 `token_cost_saving.ready`。
3. **Scale ≠ speedup**：`storage_v2_scale_evidence.passed` 不触发 `storage_v2_speedup.ready`。
4. **双臂隔离**（学 codedb）：同 client、模型、仓库、提示；唯一变量是 memory MCP 是否可用。
5. **双轴同报**：token + rubric pass / 准确率；不单报省钱。
6. **Default path 不变**：reranker、HyDE、quality profile 仍 opt-in。
7. **Observer 不阻断主路径**。

## 边界（明确不做）

| 不做 | 理由 |
|---|---|
| 照搬 codedb **−43%** 当 hm 数字 | `reference-projects.md` |
| 用 R@5 冒充 E2E 质量 | mempalace 纪律 |
| scale smoke 写成 speedup | artifact `claim_boundary` |
| 默认 reranker / HyDE | v4.2 / v3.8 |
| 复用 `BENCHMARKS.md` 已有 B10–B20 编号 | 见下表 |

### B 段编号（禁止冲突）

| 文档段 | Collection id | 说明 |
|---|---|---|
| B21 | `agent_continuation_economics` | 新；勿与 B10 `auto_maintenance` 混淆 |
| B22 | `longmemeval_e2e_qa` | 新 |
| B23 | `memory_eval_matrix_replay` | 新；勿与 B13 `storage_v2_baseline` 混淆 |
| B24 | `storage_v2_speedup_shootout` | 新；勿与 B15 `local_index_fabric_smoke` 混淆 |

---

## v5.9 — 证据地基

### v5.9.0：Bounded 文案 + 观测基建

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `harness-mem-observe.mjs` | 扫 session JSONL：hm MCP token、大 payload、missed drilldown |
| P0 | 复跑 `client_enabled_vs_disabled`（token sidecar） | **anti-overclaim** 诊断；不进 bounded/broad README |
| P1 | 复跑 `memory_shortcut` | 仅当 schema v2 / observe 接线变更；bounded 以 v4.6 accepted 为准 |
| P1 | README **bounded** 模板 | 绑定 `cost_token_evidence` / MS；**禁止**绑定 `token_cost_saving` |
| P1 | `surface_cost_report` drilldown 提示 | 估算 only |

### v5.9.1：Retrieval Quality Profile

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `retrieval_profile=quality` on MCP/config | multi-query + optional reranker |
| P0 | 分维 gate | 相对 **v5.7.3** 冻结表（或 v5.6 + 例外说明） |
| P1 | `get_project_status` 提示 quality profile | 不自动开启 |

**claim**：可说 retrieval 某维 +X pp；**不说** broad E2E（v5.11）。

### v5.9.2：B21–B24 设计包 + 文档同步

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `benchmark-suite/agent_continuation_economics/` 等四包 | prompts、claim_gate、checklist、stub driver |
| P0 | `BENCHMARKS.md` 增 **B21–B24** | publish rule + claim 表 |
| P0 | **同步** `roadmap-status.md` + Evidence Hardening 尾段 | 与本文一致 |
| P1 | `claim_promotion_pack` 扩展 | `broad_*` + 与既有 claim 互斥说明 |

---

## v5.10 — Broad Token / Cost（B21）

**Collection**：`agent_continuation_economics`

| 项 | 规格 |
|---|---|
| 任务 | ≥12 长源/跨会话 + ≥4 负控 |
| Client | **primary = Codex**；Cursor/Hermes 附录诊断（复用 v5.6 field-test 纪律） |
| Gate | 长源双 pass ≥10/12；合计 token ≥15%；median ≥20%；负控 enabled 更费 ≤1 题 |
| 稳定性 | ≤2 次 rerun；仍失败 → quarantine，不进 snapshot |
| claim | 只解锁 `broad_token_cost_saving` |

---

## v5.11 — Broad Quality

### v5.11.0 — B22 `longmemeval_e2e_qa`

| 项 | 规格 |
|---|---|
| Baseline 臂 | `no_memory_context` / `fts_only` / `hm_hybrid_real`（gate 对**最强非 hm**臂） |
| Judge | 固定 generation LLM + judge 协议（model@version、temperature、cost cap） |
| 进度 | smoke 50 → release **200** → full 500 optional |
| Gate | ≥ +5 pp 总准确率；六维回退 ≤2 pp |
| claim | `broad_memory_answer_quality` |

### v5.11.1 — B23 `memory_eval_matrix_replay`

≥20 道 Codex paired；pass ≥90%；vs disabled 准确率不降。

---

## v5.12 — Storage / Rust Speedup（B24）

**澄清**：v5.1 + v4.7 scale = **已实现**；B24 补 **宣称**证据。

| 臂 | 用途 |
|---|---|
| **生产宣称** | canonical SQLite + SearchBackend；+ Rust native vs Python fallback |
| **Maintainer 对照** | legacy JSON 路径；不进 README 主句 |

| Profile | Gate |
|---|---|
| 10k / 100k | v2 相对 legacy 非回退；Rust median ≥15% vs Python（checklist 锁定） |
| 1m | P2 / post-5.12.0 optional |

`storage_v2_speedup.ready` **仅** B24 artifact；`storage_v2_scale_evidence.passed` 不触发。

---

## v6.0 — Mature Runtime（暂定）

可搬运 bundle（A）+ 显式多项目 workspace（C）。**依赖**：v5.10 + v5.11.0 artifact 稳定后再开 `roadmap-v60.md`。

---

## Release Train

```text
v5.9.0 / 5.9.1 / 5.9.2  ─ 可并行；5.9.1 依赖 v5.7.3 分维冻结（或显式例外）
v5.10                   ─ 依赖 5.9.2
v5.11.0                 ─ 检索臂在 v5.7 后重锚；可与 5.10 并行不同 owner
v5.11.1                 ─ 依赖 5.10 paired harness 成熟
v5.12                   ─ 不依赖 agent bench；可在 5.10 之后任意时点
v6.0                    ─ 5.10 + 5.11.0 之后
```

## Release Gate

- `pytest -q`；benchmark `validate_run` + snapshot；无 `unsafe_promotions`
- 无 artifact 不写 README broad 句

## 参考文档

| 文档 | 用途 |
|---|---|
| [`roadmap-v40.md`](./roadmap-v40.md) | Storage v2 / Rust 实现 |
| [`reference-projects.md`](./reference-projects.md) | codedb 方法学边界 |
| [`../benchmark-suite/BENCHMARKS.md`](../benchmark-suite/BENCHMARKS.md) | B 段真值（B21+ 追加于此） |

## gstack 审阅结论（2026-06-18）

**approve-with-changes**（已并入上文）：B 段不冲突；claim 三线分离；scale≠speedup；5.9.0 不重复 v4.6 MS；status 页镜像 v5.10–5.12。
