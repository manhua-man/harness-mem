# Roadmap: harness-mem v2.3

> 状态：**已完成**。v2.3.0 (Signals & Replay Windows) + v2.3.1 (Metabolism Suggestion Pass) 均已落地。
>
> 主题：Signals / Replay 地基 → Suggestion 生成 → 弱链接信号应用。

---

## 目标

v2.3 只铺底层信号和 replay window，不做用户可见的新入口，也不生成会改变 truth 的建议。

这一版回答三个问题：

- 哪些记忆被 wake 展示过？
- 哪些记忆被 search 命中过？
- 哪些 candidate / skill / supersede 决策发生过，能否被后续 replay？

---

## 技术来源

- 从 `claude-mem` 借鉴：主任务不能被记忆系统拖死，后台处理必须可诊断、可恢复。
- 从 MemPalace 借鉴：所有后续整理必须能回到 raw evidence 和 provenance。
- 从 harness-mem 自身边界延续：signals 不是 truth，preview 不是 suggestion。

---

## Scope

| 领域 | v2.3 决策 |
|---|---|
| 用户入口 | 不新增 slash / 自然语言入口 |
| MCP | 新增显式 `metabolism_preview` 工具 |
| Truth | 不改 confirmed memory / rule / relation / skill |
| 信号 | 记录 retrieval / review / skill / supersede 使用事件 |
| Replay | 选择可解释输入窗口，只做 preview |
| 失败策略 | signal / preview 失败不阻断主任务 |

---

## v2.3.0：Signals and Replay Windows ✅

**用户故事**：系统能解释“为什么这批旧记忆值得回看”，而不是黑箱扫全库。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `RetrievalSignal` schema + SQLite index | 记录 `confirmed / rejected / wake_surfaced / search_hit / skill_result_* / supersede_completed` |
| P0 | `MetabolismRun` schema + SQLite index | 每次 preview run 保存 project、input window、selected signals、output counts、耗时、状态 |
| P0 | signal shadow write | 写 signal 失败只记录日志，不影响 wake/search/review 原动作 |
| P0 | replay window selector | 从 recent observations、stale candidates、historical truth、low-success skills、repeat search hits 中按预算选窗口 |
| P0 | `metabolism_preview` MCP tool | Agent 显式触发 preview，返回窗口摘要、入选理由、预算占用 |
| P1 | empty project behavior | 空项目返回空 window，并写 `MetabolismRun(status="preview")` |
| P1 | error path | selector / persistence 失败写 `MetabolismRun(status="error")`，返回 doctor pointer |

---

## Non-Goals

- 不生成 merge / stale / supersede suggestion。
- 不做 cross-project skill。
- 不做 file-context。
- 不做 wiki bridge。
- 不做 compact renderer。
- 不做 always-on daemon、IDE hook 或 turn-end 自检。
- 不改变默认 `/hm:wake`、`/hm:distill`、`/hm:search` 输出。

---

## Release Gate

- `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy harness_mem`
- `openspec validate --all --strict`
- `tests/loop_harness/` 仍通过，证明 signal shadow write 不破坏 v2.2 closed loop

---

## v2.3.1：Metabolism Suggestion Pass ✅

> OpenSpec: `openspec/changes/archive/2026-05-26-v231-metabolism-suggestion-pass/`
> 状态：已完成 (2026-05-27)

**用户故事**：系统能基于 replay window 自动产出可审核的代谢建议候选（合并 / 标 stale / supersede），同时让信号反向影响 wake/search 排序。

| 领域 | 交付物 |
|---|---|
| Suggestion schemas | `MergeSuggestionCandidate` + `StaleTruthSuggestionCandidate`（存储 + Protocol 读路径） |
| Suggestion pass | `select_metabolism_pass()` — 三路 proposer（merge entry-entry 0.85 阈值 / stale 60d 静默 / supersede deferred） |
| Token trim | `count_tokens()` tiktoken cl100k_base → char-heuristic → dim-weight 三级降级；`select_replay_window` 内容级估算 |
| Weak-link signals | `pull_recent_signals()` + wake 分组（Recent active / Stable quiet）+ search boost +0.1 + doctor 输出；`ProjectProfile.weak_link_signals` 开关（默认 off，v2.2-identical） |
| MCP tool | `metabolism_run`（写侧）— 持久化 `MetabolismRun(kind="metabolism")` + 候选；`metabolism_preview` 保持只读 |
| Back-compat | `MetabolismRun.from_dict` 兼容旧 `{"suggestions": 0}` 和新三键形态 |
| Calibration | `tests/metabolism/calibration.md` 归档阈值验证结果 |

**验证结果**：pytest 414 passed · mypy clean · ruff clean · openspec 22/22 · loop_harness 28 passed

---

## 后续归宿

| 能力 | 后续版本 |
|---|---|
| host-triggered reflection / queue health | `docs/roadmap-v24.md` |
| context assembly / file-context | `docs/roadmap-v25.md` |
| wiki bridge / compact index / contradiction suggestions | `docs/roadmap-v26.md` |
| cross-project skill / controlled activation | `docs/roadmap-v27.md` |

