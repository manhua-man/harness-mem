# Roadmap: harness-mem v2.6

> 状态：v2.6.1 已完成；v2.6.2+ 仍在规划中。
>
> 主题：Wiki Bridge + Compact Index + Contradiction Suggestions。把长期知识从权威源编译成可检索上下文，并把冲突处理保持在 candidate 层。

---

## 目标

v2.6 吸收 `ai-harness` 的 source cache / generated cache 边界，以及 MemPalace 的 closet -> drawer 和 contradiction 思路。

这一版不是做桌面 UI，也不是把 Markdown 目录变成 source of truth。它的目标是：从 accepted memory 和 curated docs 编译出可读、可搜索、可追溯的知识输出。

---

## 技术来源

- `ai-harness`：`source docs -> Sync-MemoryCache -> knowledges-cache -> Refresh-MemPalace -> .mempalace_local/palace`。
- MemPalace：closet -> drawer、raw/verbatim、temporal KG、contradiction detection、AAAK renderer 边界。
- harness-mem：candidate-before-truth、supersede/current-history、source observation ids。

---

## Scope

| 领域 | v2.6 决策 |
|---|---|
| Knowledge Cache | 区分 manual / generated |
| Wiki Bridge | 编译 accepted memory + curated docs，不写 runtime truth |
| Compact Index | 短 claim / topic / entity 索引指向 source |
| Contradiction | 只生成 suggestion / candidate，不直接改 truth |
| Renderer | compact / AAAK 类输出只做渲染，不做 canonical storage |

---

## v2.6.0：Knowledge Cache Boundary

**用户故事**：长期知识可以编译，但人工权威源和 AI 生成物不会混在一起。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | source cache design | 定义 accepted memory、curated docs、generated knowledge cache 的边界 |
| P0 | manual/generated split | 人工维护内容和脚本生成内容分目录、分 authority |
| P0 | sync map visibility | 映射规则能被 docs index 或 doctor 看见 |
| P1 | source hash | 支持增量编译和 stale detection |
| P1 | generated cache cleanup | 删除过期 generated 输出不影响 canonical storage |

### 当前实现（2026-05-31）

- 已实现 project-scoped `knowledge-cache/manual/` 与 `knowledge-cache/generated/` 分层。
- 已实现 `sync-map.json` + `source-manifest.json` + generated `index.json`。
- 已实现 `ProjectProfile.curated_doc_paths` 作为 manual curated docs 入口。
- 已实现 `harness-mem doctor` 的 knowledge-cache visibility block。
- 已实现 `maintenance prepare-knowledge-cache` 与
  `maintenance cleanup-generated-cache`。
- wiki compiler / compact claim index 仍未在 v2.6.0 内实现；这些由 v2.6.1 补齐。

## v2.6.1：Wiki Bridge and Compact Claim Index

**用户故事**：Agent 可以先看到短 claim 和来源，再决定是否展开原始 observation / memory。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | wiki bridge compiler | `accepted memory + curated docs -> generated knowledge cache` |
| P0 | compact claim index | claim / topic / entity / source ids 可搜索 |
| P0 | drawer-style drilldown | 每条 claim 能回到 observation / memory / doc source |
| P1 | no hidden truth | generated wiki 不会被 wake 当作 confirmed truth |
| P1 | docs for authority levels | 用户能理解 manual、accepted memory、generated cache 的区别 |

### 当前实现（2026-06-02）

- 已实现 `rebuild_wiki_bridge(...)`，从 accepted memory、confirmed rules、relation facts
  和 curated docs 编译 generated wiki bridge。
- 已实现 `knowledge-cache/generated/claims.json`、`topics.json`、`entities.json` 与增强版
  `generated/index.json`。
- 已实现 claim -> source drilldown，source 可回到 `memory_entry_id`、`confirmed_rule_id`、
  `relation_fact_id` 或 `curated_doc_path`。
- 已实现 `maintenance rebuild-wiki-bridge` 显式重建入口。
- 已实现 doctor 对 generated claim/topic/entity 计数的可见性。
- 已验证 generated wiki 不进入默认 `wake` / `search_memory` truth surface。

## v2.6.2：Contradiction and Stale Suggestions

**用户故事**：系统能发现疑似冲突、重复、过期，但必须先给出可审核建议。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | contradiction detector | 新旧 truth 冲突时生成 suggestion，不 mutate truth |
| P0 | stale suggestion | 过期 path、命令、决策生成 supersede / stale candidate |
| P0 | merge suggestion | 重复 memory / relation 生成可审核合并建议 |
| P1 | evidence bundle | 每条 suggestion 带 source ids 和 reasoning |
| P1 | review surface | `/hm:review` 区分普通 candidate 和 metabolism/wiki suggestions |

## v2.6.3：Compact Renderer Experiment

**用户故事**：需要低 token wake 时，可以用 compact renderer，但原文证据永远可追溯。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P1 | compact wake format | 输出短摘要、entities、topics、source ids |
| P1 | AAAK-like renderer experiment | 只作为 renderer，不进入 storage truth |
| P1 | quality checks | compact mode 不得丢失 source id 或冒充 verified truth |

---

## Non-Goals

- 不做 cloud wiki。
- 不做 desktop memory palace UI。
- 不用 Markdown directory 替代 SQLite / structured store。
- 不让 generated wiki 变成 confirmed truth。
- 不让 contradiction detector 直接删除或改写 accepted memory。

---

## 后续归宿

| 能力 | 后续版本 |
|---|---|
| cross-project procedural skill | `docs/roadmap-v27.md` |
| controlled skill activation / shared skill hints | `docs/roadmap-v27.md` |
