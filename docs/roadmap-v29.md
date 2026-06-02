# Roadmap: harness-mem v2.9

> 状态：v2.9.0 / v2.9.1 已完成。
>
> 主题：PRD Sync Candidate Surface。把已有的 `prd-sync` 半成品脚本收束成
> 正式的 `/hm:prd-sync` 维护入口：默认 dry-run，只生成 candidate，不直接改
> PRD/roadmap 或 confirmed truth。

---

## 目标

当前 repo 已经在 `tools/session-distill/bin/session-distill.py` 里放了一个
`prd-sync` 命令：

- 它会扫描 `bundled` packets
- 它会识别 PRD / roadmap / scope / architecture 一类关键词
- 它可以在 `prd-distilled/` 下生成候选 markdown

但这块能力仍然停留在“脚本里有命令”的阶段，还没有正式产品面真值：

1. 没有 slash / 自然语言入口说明。
2. 没有 OpenSpec contract。
3. 没有 focused tests。
4. 没有清晰边界来说明它只能产 candidate，不能直接改正式文档。

v2.9 的目标不是扩新记忆类型，而是把这条现有维护面收成正式、可验证的
candidate surface。

---

## Scope

| 领域 | v2.9 决策 |
|---|---|
| Entry surface | 新增 `/hm:prd-sync [--apply]` 作为维护入口 |
| Input boundary | 只读取 session-distill manifest 中 `bundled` packet |
| Default behavior | 默认 dry-run，只预览命中的 packet 和 topic |
| Apply behavior | `--apply` 只写 `prd-distilled/*.md` candidate 文件 |
| Mutation boundary | 不直接改 PRD、roadmap、knowledge-base 或 confirmed truth |
| Workflow position | 属于 maintenance / review bridge，不属于 `/hm:distill` 主链 |

---

## v2.9.0：PRD Sync Candidate Surface

**用户故事**：当 bundled packets 里已经出现了 PRD、roadmap、scope、architecture
类讨论时，Agent 可以先生成一份 candidate PRD sync note，让后续产品文档整理有
依据，但不会越权直接改正式 PRD 或 roadmap。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `/hm:prd-sync` entry contract | 成为正式维护入口，而不是隐藏脚本 |
| P0 | dry-run default | 默认只预览，不写文件 |
| P0 | candidate-only apply | `--apply` 只写 `prd-distilled/*.md` |
| P1 | projectless maintenance boundary | 不要求项目 cwd 解析才能运行 |
| P1 | focused regression tests | 覆盖 no bundle / dry-run / apply / bundled-only scanning |

### 当前状态（2026-06-02）

- 已完成 `openspec/changes/v290-prd-sync-candidate-surface/`。
- `/hm:prd-sync [--apply]` 已进入 README、plugin command、session-distill
  references 与 OpenSpec 主 contract。
- `prd-sync` 现在明确是 projectless maintenance entry：
  - 默认 dry-run
  - `--apply` 只写 `prd-distilled/*.md`
  - 不直接改正式 PRD、roadmap、knowledge-base 或 confirmed truth
- 已补 focused tests，覆盖：
  - no bundled packets
  - dry-run 不写文件
  - apply 只写 candidate markdown
  - 只扫描 `bundled` sessions

## v2.9.1：Status Triage Surface

**用户故事**：用户运行 `/hm:status` 时，看到的是一个稳定的、只读的项目记忆分诊入口，而不是不同文档各说各话的“也许是 doctor，也许是 MCP status”的混合面。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `/hm:status` contract | 成为正式 read-only triage 入口 |
| P0 | MCP triage hints | `get_project_status` 返回 `phase` / `suggested_slash` / `reason` |
| P0 | review-only hint boundary | pending candidates 只追加 repair hint，不把 `/hm:review` 升成主 happy path |
| P1 | doc alignment | plugin README、slash command、roadmap 与真实 MCP 行为一致 |

### 当前状态（2026-06-02）

- 已完成 `openspec/changes/v291-status-triage-surface/`。
- `/hm:status` 现在正式收束成 read-only triage surface。
- MCP `get_project_status` 现在会返回：
  - `phase`
  - `suggested_slash`
  - `reason`
  - 可选 `repair_hint` / `repair_reason`
- triage 语义锁定为：
  - empty project → `/hm:distill`
  - ready project → `/hm:wake`
  - pending candidates → 只作为 repair-only `/hm:review` hint

---

## Non-Goals

- 不让 `prd-sync` 直接编辑正式 PRD 或 roadmap 文档。
- 不让 `prd-sync` 写 confirmed rule / memory / relation / skill truth。
- 不把 `prd-sync` 做成 `/hm:distill` 主链的一部分。
- 不引入新的 daemon、scheduler 或后台自治文档同步。

---

## 与既有版本线的关系

| 能力 | 依赖 |
|---|---|
| `/hm:distill` 主链 | `docs/roadmap-v22x.md` |
| host-triggered reflection / doctor | `docs/roadmap-v24.md` |
| shared skills / controlled activation | `docs/roadmap-v27.md` |
| session-distill maintenance family | `docs/roadmap-v28.md` |

v2.9 是对 session-distill maintenance family 的补片：从 bundled packet 到
产品文档整理之间，补一个 candidate-only 的桥，而不是开启新的自治写面。
