# Roadmap: harness-mem v3.2

> 状态：已发布，当前版本 3.2.0。
>
> 主题：Generated Knowledge Compiler + Basic Freshness。把 v2.6 wiki bridge
> 从“可用的 compact generated cache”推进成可诊断、可增量、可引用的项目知识编译链；
> 同时提前补最小 freshness / compile metrics，避免 generated layer 到 v3.4 才可见。

---

## 目标

v3.2 的目标不是把 wiki prose 变成 memory truth，也不是把外部参考表做成产品能力；
它只收一个必要功能：让项目知识派生层更像一个编译器。

```text
accepted memory + curated docs + repo structure signals
-> source map
-> atomic claims / modules / citations
-> generated wiki / compact context
-> freshness / compile metrics + drilldown
```

参考线：

- `codedb-mcp`：project-local generated layer、module_map / atlas、DeepWiki、tool-cost observer。
- `llm_wiki`：two-step ingest、source traceability、incremental cache。
- `meta-kb`：atomic claims、citation 校验、content-hash incremental compile。

## 边界

- generated wiki / compact page 不是 truth。
- 不把 agent reasoning 写进 accepted memory。
- 不把 `reference-projects.md` maintainer 总表当 v3.2 产品切片；参考项目维护留在参考文档。
- 不要求默认接入代码知识 MCP；只定义 `harness-mem` 自己的 generated cache 边界。
- 不把 Markdown directory 反转成 source of truth。
- 不做 full module atlas、cloud wiki 或团队协作 UI。
- 不做完整 dashboard；v3.2 只给 generated compile/freshness 的基础可见性。

## v3.2.0：Source Map and Generated-Layer Boundary

**用户故事**：Agent 能解释每条 generated claim 来自哪些 source，维护者能确认派生物没有混进 truth。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | source map schema | 每个 generated source 记录 kind、path/id、content hash、mtime、provenance |
| P0 | generated/source separation | generated 输出不能冒充 curated docs 或 accepted truth |
| P0 | generated cache root discipline | generated artifacts 有明确落点，cleanup 删除派生物不触碰 observations / confirmed truth |
| P1 | readable source-map export | doctor 或维护命令能展示 source -> claim/wiki/compact 的映射 |

### 当前实现（2026-06-07）

- 已实现 `knowledge-cache/generated/source-map.json`，记录 source kind、path/id、
  content hash、mtime、provenance、claim ids 与 invalid claim ids。
- generated 输出继续落在 project-scoped `knowledge-cache/generated/`；manual/source
  manifest 保持分层，cleanup 只删除 generated root 下的 orphaned outputs。
- `doctor` 与 `maintenance rebuild-wiki-bridge` 已能展示 source map / generated compiler
  的基础可见性。

## v3.2.1：Atomic Claim Compiler

**用户故事**：wiki bridge 先产生可验证的短 claim，再生成 prose 页面。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | atomic claim shape | claim 包含 text、source ids、citation spans、confidence、staleness metadata |
| P0 | citation validation | 无 source / source hash drift 的 claim 不进入 compact wake material |
| P0 | no direct prose truth | wiki prose 只消费 claim，不反向写 accepted memory |
| P1 | claim diff | rebuild 后能显示 added / removed / changed claims |

### 当前实现（2026-06-07）

- `claims.json` 的每条 claim 已包含 `text`、`source_refs`、`citation_spans`、
  `confidence`、`staleness`、`content_hash` 和 `cache_status`。
- compact wake loader 会校验 source id 与 source hash；无 source、无 citation 或 hash drift
  的 claim 不进入 compact wake material。
- rebuild 写 `claim-diff.json`，显示 added / removed / changed / unchanged claims。

## v3.2.2：Incremental Cache and Basic Freshness

**用户故事**：只改一份 source 时，不需要重编整个知识缓存，也能知道哪些输出过期。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | content-hash incremental compile | source hash 未变时复用已有 claim/module 输出 |
| P0 | freshness status | doctor/status 显示 stale sources、orphaned generated outputs、hash drift |
| P0 | cleanup remains non-truth | cleanup 只删 generated artifacts，不删 observations / confirmed truth |
| P0 | basic compile metrics | 记录 compile duration、source count、claim count、cache hit ratio |
| P1 | output-cost estimate | 估算 generated compact 输出 token，供 v3.4 cost observer 复用 |

### 当前实现（2026-06-07）

- rebuild 根据 source hash 与 claim content hash 标记 `cache_status=compiled/reused`，
  并记录 cache hit ratio。
- `index.json` 记录 compile duration、source count、claim count、invalid claim count、
  cache hit/miss count、cache hit ratio 和 output token estimate。
- `knowledge_cache_health`、`doctor`、`status` 与 MCP `get_project_status` 显示 stale source、
  missing source、orphaned generated output、invalid claim 和 compiler metrics。

## v3.2.3：Generated Context UX and Minimal Structure

**用户故事**：Agent 可以按需消费 generated knowledge，但默认 wake 仍只吃 confirmed current truth。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | compact context drilldown | compact claim 能跳回 memory/doc/source map |
| P0 | wake boundary | generated context 默认不进 normal wake；compact wake 必须显式 opt-in |
| P0 | `/hm:status` visibility | status 只提示 generated cache freshness，不制造用户待办 |
| P1 | minimal module grouping | 仅在证据足够时输出 module/source group、entry points、why grouped；弱证据标记 inferred / uncertain |
| P2 | optional external-code-intel hook | 外部 code intelligence 只作为 evidence input，不成为 truth，不作为 v3.2 release blocker |

### 当前实现（2026-06-07）

- compact context 继续通过 `wake(renderer="compact")` 显式 opt-in；默认 wake / search 仍只消费
  confirmed current truth。
- compact claim 保留 source refs / citation spans / drilldown，可回到 memory entry、confirmed rule、
  relation fact 或 curated doc。
- status 只提示 generated cache freshness，不制造新的用户待办。
- minimal module grouping 与 external code-intelligence hook 未纳入 v3.2.0 release blocker。

---

## Release Gate

- `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy harness_mem`
- Focused tests:
  - source map schema
  - citation validation
  - generated prose not truth
  - incremental hash reuse
  - freshness doctor
  - basic compile metrics
  - compact context drilldown

---

## 一句话

v3.2 是 wiki bridge 的编译器化：先 source map 和 atomic claims，再 prose 和 compact context；generated layer 永远可追溯、可清理、可诊断，但不替代 accepted truth，完整图谱和完整 dashboard 后置。
