# v161-bucket-budget-and-distill-readonly

## Why

`v1.6.0`（已归档 `2026-05-17-v160-eval-and-typing`）落地了"测量地基 + 记忆分型 schema"，但显式地把 wake-up / search / distill 的**行为**变更推迟到了本切片：

- `MemoryEntry.memory_type` 已经是一等字段（`semantic / episodic / procedural`），但 wake-up 还是按全库 recency + importance 选 top-5，semantic 规则会被海量 episodic observation 挤出预算
- search 三端只**暴露** `memory_type`，但还不支持按它 filter
- distill 路径理论上能直接调用 `ConfirmedRuleStore.delete / .update`，没有显式只读边界

`docs/roadmap-v16x.md` 与 vision 文档（[`docs/roadmap-vision-v16-v18.md`](../../../docs/roadmap-vision-v16-v18.md)）对本切片的强约束是：

> **安全边界必须先于能力增强落地**——一旦 v1.6.2 引入持久化向量后 distill 能"读全库 + 跑聚类"，写边界没锁死就会被诱惑去"顺手清理一下"。

所以本 change 一次性把"用户体验上的写边界（distill 只读）"与"用户体验上的读分桶（wake-up 三桶预算）"绑成一个切片，避免任何一项单独发版的诱惑。

## What Changes

- **wake-up 分桶预算**：`[wake]` 配置增加 `bucket_quota_semantic / bucket_quota_episodic / bucket_quota_procedural`，默认 `0.5 / 0.5 / 0.0`（已决策，见 `roadmap-v16x.md`"已决策 2"）；`bucket_quota_enabled` 默认 `true`。`select_wake_memory_entries` 改为**按 `memory_type` 分桶 + 每桶独立 token 配额 + 桶内截断**；超额不挤占其他桶。
- **wake-up 输出标注**：wake header 显示当前配额比例与实际填充率；桶内截断时显式标注 `[truncated within bucket: episodic 3/8]`，延续 v1.5.1 截断显式标注的精神。
- **wake-up bucket 显式可关**：CLI flag `harness-mem wake --no-bucket-quota` 与 config `[wake] bucket_quota_enabled = false` 把行为退回 v1.6.0（全库混排 top-k）。
- **search 按 memory_type filter**：MCP `search_memory` / REST `/search` / CLI `search` 三端增加 `memory_type=episodic|semantic|procedural` 可选参数；默认行为不变（不过滤）。
- **distill 只读边界（DistillContext）**：在 `harness_mem.distill_context` 引入 `DistillContext` 接口，仅暴露 `read_observations / search / compare / suggest_*`；尝试从 distill 路径直接 mutate `ConfirmedRule / RelationFact / Observation` 的写动作 MUST 抛 `DistillReadOnlyError`。
- **distill 写动作降级为候选**：`distill_session / distill_relation_facts` 的所有"建议"路径改写候选层（`RuleCandidate / MergeSuggestion`），且每条建议必须有 `reviewer_id / confirmed_at / rejected_at` 字段（已在 schema 上）。`MergeSuggestion / ConflictCandidate / SupersedeCandidate` 至少先有 `RuleCandidate / MergeSuggestion` 两类，其它在 v1.6.1 是 placeholder。
- **配置错误码**：`bucket_quota_*` 总和 ≠ 1.0 时 `harness-mem doctor` 输出 `HM-101 wake bucket quotas must sum to 1.0`；与现有 `HM-001 / HM-002 / HM-003` 同表登记。
- **CHANGELOG 草稿** + 五维不回退验收。

## Out of Scope

- **持久化向量索引（sqlite-vec）**——v1.6.2
- **embedding 模型升级**——v1.6.2
- **bi-temporal `valid_from / valid_to / supersedes`**——v1.7
- **`procedural` 类型的实际产生路径**——v1.8（vision 已划界）
- **跨项目共享 bucket 配额**——没有用户场景
- **自治删 truth / Proactive runtime**——vision + dream-absorption 文档明确不做
- **MergeSuggestion / ConflictCandidate / SupersedeCandidate 的完整实现**——本切片只确保 RuleCandidate 与 MergeSuggestion 两类候选的写边界，其余落到 v1.7
