# Roadmap: harness-mem v3.6

> 状态：已完成。
>
> 主题：Generated Claim Hardening。把 v3.2 generated compiler 从"能生成 compact
> knowledge"推进到"claim-first、citation-verified、freshness-aware"。

---

## 目标

v3.6 不把 generated wiki 变成 truth。它强化的是 generated layer 的可信度：

```text
curated docs / accepted memory
-> atomic claims
-> source map + citation verification
-> freshness / drift checks
-> compact renderer / wiki prose
```

参考线：

- `meta-kb`：claims-first、citation verification、自评迭代。
- `llm_wiki`：two-step ingest、source traceability、incremental cache、review queue。
- `codedb-mcp`：project-local generated layer、source map、prose 由结构层派生。
- `ai-harness`：manual/generated 分层，运行产物不当协作源。

## 边界

- generated claim / wiki prose 不是 confirmed truth。
- 不让 AI 直接把 generated claim 写进 durable truth。
- 不隐藏 source map；没有可验证 source 的 claim 不进 compact wake。
- 不把 prose-first wiki 当 canonical storage。
- 不把 cleanup-generated-cache 扩成清理 observations 或 confirmed truth。

## v3.6.0：Claim-First Compiler Contract

**用户故事**：每条 generated knowledge 都能追到 atomic claim 和 source。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | claim schema hardening | claim 记录 source ids、content hash、mtime、provenance、authority |
| P0 | prose-after-claim rule | wiki / compact prose 只能由 validated claims 派生 |
| P0 | generated authority labels | 输出显式标记 generated summary，不冒充 confirmed truth |
| P1 | source coverage report | 报告 claim 覆盖哪些 curated docs / accepted memory |

**实现说明**：`rebuild_wiki_bridge()` 继续先写 source map / atomic claims，再写 topic、
entity 和 compact material；claim payload 带 `source_refs`、`citation_spans`、
`content_hash`、`staleness` 和 `authority=generated_claim`。

## v3.6.1：Citation Verification

**用户故事**：citation 失效或 hash drift 时，系统宁可少输出，也不输出假确定性。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | citation validator | 校验 source id、hash、excerpt range 或 equivalent provenance |
| P0 | invalid claim exclusion | invalid / drifted claim 不进入 compact wake 和 generated result |
| P0 | doctor/status visibility | status 显示 invalid citation、hash drift、stale source 数量 |
| P1 | repair hint | 给出 rebuild / review / source update 建议，但不自动改 truth |

**实现说明**：compact loader 会校验 source id 与 hash；hash drift / invalid citation
的 claim 不进入 compact wake，`knowledge_cache_health()` 会把这些项放进
`generated_review_queue`。

## v3.6.2：Freshness and Review Queue

**用户故事**：维护者知道 generated layer 哪些旧了、哪些需要重编、哪些需要人工看。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | freshness windows | source mtime/hash 变化后标记 stale claim |
| P0 | generated review queue | 高风险、低 coverage、citation drift 的 claim 进入 review surface |
| P0 | incremental rebuild discipline | rebuild 复用未变 claims，更新 changed claims |
| P1 | claim diff UX | 人类能看懂新增、删除、变更和失效 claim |

**实现说明**：`claim-diff.json`、compile metrics、`cache_hit_ratio`、`hash_drift_count`
与 `generated_review_queue_count` 都进入 health/status 可见面。

## v3.6.3：Compact Renderer Trust UX

**用户故事**：Agent 使用 compact generated context 时，能看见来源、预算和剩余 drilldown。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | compact output trust block | 输出 authority、source ids、claim count、freshness summary |
| P0 | drilldown pointers | 每个 compact topic 可继续查 source claim / original observation |
| P1 | budget integration | compact renderer 与 v3.4 cost budget 共用 token estimate 和 truncation metadata |

**实现说明**：`render_compact_wake_payload()` 输出 `# Trust`、`# Source IDs` 和
`# Drilldown`，明确 generated summary 不是 confirmed truth，并保留 source drilldown。

## 一句话

v3.6 让 generated knowledge 更可信，但仍然守住边界：generated layer 可以帮 agent 理解项目，
不能替代 confirmed truth。
