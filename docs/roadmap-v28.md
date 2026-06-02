# Roadmap: harness-mem v2.8

> 状态：OpenSpec skeleton 已创建，代码未开始。
>
> 主题：Session-Distill Maintenance Surfaces。把 `/hm:mark`、`/hm:prune`、
> `/hm:review-kb`、`/hm:prune-kb`、`/hm:verify-entry` 从 repo-local tool 约定收束成
> 版本化、可验证的正式产品面。

---

## 目标

v2.8 不再扩展新的记忆类型，而是收紧 distill 后处理面的产品真值。

当前 repo 已经在这些位置把 distill 维护入口当成一等用户工作流：

- `README.md`
- `AGENTS.md`
- `plugins/harness-mem/README.md`
- `plugins/harness-mem/commands/hm/*.md`
- `tools/session-distill/SKILL.md`
- `tools/session-distill/bin/session-distill.py`

但这些能力目前主要活在 repo-local script 与 slash 文档里，还没有一条像 v2.2-v2.7
那样的正式 roadmap / OpenSpec 版本线来约束：

1. session closure 的 guardrail 到底哪些是硬 gate。
2. manifest cleanup 可以改什么，绝不能改什么。
3. knowledge-base review / prune / verify 的状态模型和备份契约。
4. 轻提醒和 review baseline 属于什么级别的 runtime promise。

v2.8 的目的就是把这些维护能力从“工具存在 + 文档提到”升级成“正式产品面，有边界，
有验收，有测试口径”。

---

## Scope

| 领域 | v2.8 决策 |
|---|---|
| Session closure | `/hm:mark` 是关闭单个 session 的正式入口，带 note/draft/KB guardrail |
| Manifest cleanup | `/hm:prune` 只清理 source-missing 的已处理占位，不碰 canonical truth |
| KB review | `/hm:review-kb` 负责稳定性分类与 baseline 更新 |
| KB cleanup | `/hm:prune-kb` 先备份，再清理 `stale/superseded` 条目 |
| KB verification | `/hm:verify-entry` 只做 grill-style 复查，不静默删除 |
| Reminder surface | review-kb / verify-entry 轻提醒只进摘要，不升级成强 gate |

---

## v2.8.0：Session Closure and Manifest Cleanup

**用户故事**：一次 distill 跑完之后，Agent 可以把单个 session 安全收口成
`distilled`，并清理 raw 已不存在的 manifest 占位，但不会误删 raw 或把未完成 session
伪装成已完成。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `/hm:mark` guardrail contract | `distilled` 收口前必须过 session note / raw review / promotion / draft / KB guardrail |
| P0 | manifest status model | `distilled/skipped` 与 `source_missing/raw_deleted_at` 的语义固定 |
| P0 | `/hm:prune` cleanup boundary | 只清理 raw 已不存在、且已处理状态的 manifest 占位 |
| P1 | raw deletion whitelist | 只有显式 mark 流程可删 raw，`--keep-raw` 保留原件 |
| P1 | maintenance summary | 输出可执行摘要，不把底层脚本参数暴露成产品心智模型 |

### 当前真值（2026-06-02）

- 用户文档和 plugin 命令已经把 `/hm:mark` / `/hm:prune` 当作正式入口。
- repo-local 实现主要位于 `tools/session-distill/bin/session-distill.py`。
- 相关提示词与 guardrail 已写进 `tools/session-distill/SKILL.md`，但尚未进入主 OpenSpec。

## v2.8.1：Knowledge-Base Review and Prune

**用户故事**：knowledge-base 需要像候选层一样有可审计的巡检和清理流程，而不是手工编辑一个不断膨胀的 markdown 文件。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `/hm:review-kb` status model | 条目明确落到 `stable / needs-review / stale / superseded` |
| P0 | review baseline state | 记录上次 review 时间、条目数、状态摘要 |
| P0 | `/hm:prune-kb` backup-first | 清理前自动备份 knowledge-base |
| P1 | prune confinement | 只删 stale/superseded 条目，不碰其他产物 |
| P1 | review summary | 输出下一步建议：是否该 verify-entry 或 prune-kb |

## v2.8.2：Targeted Verification and Reminder Surfaces

**用户故事**：新 packet、新 note 或大量新 knowledge 出现时，系统可以提醒“该复查哪里”，但不会自动清理或打断主任务。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `/hm:verify-entry` targeted review | 可按 session id 或关键词命中 knowledge 条目并输出复查问题 |
| P0 | reminder thresholds | 新增 5 条 KB / packet-keyword overlap / note overlap 的轻提醒 |
| P1 | summary-only reminders | 提醒只进入摘要，不自动 prune、不自动 supersede |
| P1 | doctor / health reuse | 维护建议与既有 doctor next-step 文案保持一致 |

---

## Non-Goals

- 不把这些维护入口重新做成日常 CLI 主工作流。
- 不让 `/hm:mark`、`/hm:prune-kb`、`/hm:verify-entry` 直接改 confirmed truth。
- 不把 review-kb 分类自动映射成 relation/rule/memory 的静默删除。
- 不把轻提醒升级成后台 daemon 或强阻断。

---

## 与既有版本线的关系

| 能力 | 依赖 |
|---|---|
| `/hm:distill` 主链 | `docs/roadmap-v22x.md` |
| host-triggered reflection / doctor | `docs/roadmap-v24.md` |
| context assembly / file-context | `docs/roadmap-v25.md` |
| knowledge cache / wiki bridge | `docs/roadmap-v26.md` |
| shared skills / controlled activation | `docs/roadmap-v27.md` |

v2.8 不是替代这些版本，而是把 distill 后处理与 knowledge audit 从
repo-local tool 约定提升成正式 runtime contract。
