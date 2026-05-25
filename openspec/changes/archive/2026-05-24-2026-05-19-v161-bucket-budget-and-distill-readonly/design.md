# Design notes — v161 bucket budget + distill read-only

## 1. wake-up 分桶预算

### 1.1 预算模型

v1.6.0 之前 wake-up 选 5 条 entry 走的是单一 `select_wake_memory_entries`：先按 importance 保护性占位 1-2 条，再按 recency 填满到 limit。这个模型对 token 没有"硬上限"，只对 entry 数有"软上限 5"。

v1.6.1 改成"按 `memory_type` 分桶 + 每桶独立 token 配额"：

```
total_token_budget := chars_to_tokens(legacy budget L0..L3 hint)  # 暂沿用既有 disclosure level，不重新设计
per_bucket_token_quota[bucket] := total_token_budget * bucket_quota[bucket]
```

`bucket_quota` 默认 `{"semantic": 0.5, "episodic": 0.5, "procedural": 0.0}`，总和必须 = 1.0。

为简化阅读路径与最小行为变更面，v1.6.1 仍由 `select_wake_memory_entries` 返回 entry 列表（不直接消费 token quota）：

- 在 entry 数量这一层：每个 bucket 至少分到 `floor(limit * quota)` 个名额（procedural=0 时为 0）；剩余不足的桶把名额让给其他桶
- 在 token 这一层：当前 baseline 的 `wake_budget` 计算在 entry 输出 **之后** 做（仅作为 disclosure level 提示），v1.6.1 不强制改变这个计算路径
- 桶内截断：每个桶用现有 importance + recency 排序，超过该桶名额的 entry 被丢掉，输出标注 `[truncated within bucket: <type> X/Y]`

这种"先 entry 名额再 token estimate"的模型保留了 v1.5.x 的输出形态，避免把 v1.6.1 变成 wake 系统大重写。token-aware 分桶在 v1.6.2 sqlite-vec 落地后再迭代。

### 1.2 fallback 行为

- 当 `bucket_quota_enabled=false`（CLI `--no-bucket-quota` 或 config 显式关闭）时，`select_wake_memory_entries` 完全等价于 v1.6.0 行为
- 当某桶配额 > 0 但无候选时，未消费名额按 `semantic > episodic > procedural` 优先级让给下一个桶（避免空桶占预算）

### 1.3 输出 header

```
# Memory Entries  (source: structured_memory, 5 entries, ~480 chars)
#  bucket quotas: semantic=0.50 episodic=0.50 procedural=0.00
#  bucket fill:   semantic=2/3 episodic=3/2 procedural=0/0
- [convention/semantic] use single quote ...
- [bug/episodic] auth failure trace ...
- ...
[truncated within bucket: episodic 3/8]
```

`fill` 行格式：`<type>=<used>/<quota_count>`，`quota_count = floor(limit * quota)` 在配额让渡前的原始名额。

## 2. distill 只读边界

### 2.1 边界模型

v1.6.0 的 distill 路径调用栈：

```
cmd_distill -> ClaudeCodeAdapter.distill_session -> backend.structured_store.save_memory_entry / save_relation_fact
```

理论上 distill 现在可以直接调 `ConfirmedRuleStore.delete / .update`，没有任何静态边界。本切片在 distill 入口处构造 `DistillContext`：

```python
class DistillContext:
    """Read-only view + suggestion-only write surface for distill paths."""

    def __init__(self, backend: LocalMemoryBackend) -> None:
        self._backend = backend

    # read paths -- explicitly delegated
    async def read_observations(...)
    async def search(...)
    async def list_confirmed_rules(...)
    async def list_relation_facts(...)
    async def compare(...)  # 占位：v1.7 supersede 用

    # write paths -- only candidate layer
    async def suggest_rule(...) -> RuleCandidate
    async def suggest_memory_entry(...) -> MemoryEntry  # status="pending"
    async def suggest_merge(...) -> MergeSuggestion

    # 任何对 ConfirmedRule / RelationFact / Observation 的直接写都必须经由 DistillContext.suggest_*；
    # 直接拿 backend.structured_store 调用 .save / .delete / .update 不会被静态阻断（Python 动态），
    # 但是 distill 入口 cmd_distill 与 ClaudeCodeAdapter.distill_* 只接收 DistillContext，不再接收
    # 完整 backend；这是"约定 + 类型注解 + 边界单测"三层防御。
```

`DistillReadOnlyError` 是为了在边界单测里用 monkeypatch 故意调用 backend 写方法时**显式失败**，而不是依赖"恰好不会调"——防御性。

### 2.2 写动作降级

v1.6.0 `distill_session` 直接 `await self.backend.structured_store.save_memory_entry(entry)`；status 已经默认是 `"accepted"`。v1.6.1 把这条路径切到候选层：

- distill 产生的 `MemoryEntry` MUST 写入时 `status="pending"`，由用户/AI 通过 `confirm_memory_entry` 转 `accepted`
- distill 产生的 `RuleCandidate` 不变（已经走候选层）
- distill 产生的 `RelationFact` MUST 写入时 `status="pending"`（schema 已支持）

为了不破坏现有 CLI dogfood 流程（`harness-mem distill` 当前默认产出可立即被 wake-up 看到），引入 `--auto-confirm` flag：开发者本地可继续用旧行为。**默认行为**改为产出 pending 候选，CHANGELOG 显式标注 breaking 改动。

### 2.3 与 v1.7 的衔接

`DistillContext.compare(...)` 在 v1.6.1 仅返回 `(left, right, diff_summary)`，不消费时间字段；v1.7 引入 `valid_from / valid_to` 后再扩展为 `supersede` 候选生成。

## 3. search 按 memory_type filter

`search_memory_entries(query, project_name, ..., memory_type: list[str] | None = None)` 在 SQLite 层 `WHERE memory_type IN (...)`；为空/None 时不过滤。

MCP `search_memory` 工具签名：

```
search_memory(query: str, project_name: str | None = None, scope: str = "project",
              mode: str = "auto", memory_type: list[str] | None = None, ...)
```

REST `/search` 接受 `memory_type=semantic&memory_type=episodic` 或单值；CLI `harness-mem search "x" --memory-type semantic --memory-type episodic`。

## 4. 配置错误码

`harness-mem doctor` 在 v1.5.3 已经登记 `HM-001 / HM-002 / HM-003`；本切片新增：

- `HM-101 wake bucket quotas must sum to 1.0`：当 `[wake]` 段的 `bucket_quota_*` 总和不在 `[0.999, 1.001]` 容差范围内时
- `HM-102 wake bucket quota out of range`：单值 < 0 或 > 1 时

修复命令统一指向 `~/.harness-mem/config.toml` 的 `[wake]` 段，并提示默认值 `0.5 / 0.5 / 0.0`。

## 5. 测试矩阵

| 模块 | 测试文件 | 关键 Scenario |
|------|---------|--------------|
| wake bucket | `tests/wake/test_bucket_budget.py` | 默认配额 / 关闭配额 / 单桶溢出截断 / 桶让渡 / 配额非法 |
| distill 边界 | `tests/distill/test_readonly_boundary.py` | DistillContext 不暴露 .delete / .update / 边界绕过 raise |
| distill 候选 | `tests/distill/test_candidate_layer.py` | distill_session 默认产 pending / `--auto-confirm` 兼容老流程 |
| search filter | `tests/integration/test_search_memory_type_filter.py` | CLI / MCP / REST 三端契约 + 默认不过滤 |
| doctor 错误码 | `tests/cli/test_doctor_codes.py`（追加） | HM-101 / HM-102 触发条件 |

## 6. baseline 与回归判定

- 跑 `python -m harness_mem.tools.longmemeval <dataset> --mode hybrid --top-k 5 --use-real-hybrid` 与 `docs/benchmark/v160-baseline.md` 的 `hybrid (real)` 列对比
- 通过判据：总 R@5 与 ≥ 4 维度不回退；至多 1 维度小幅波动 ≤ 2 pp。**注**：分桶预算只影响 wake-up，理论上不直接进入 LongMemEval corpus 评分（LongMemEval 评的是 search recall，不是 wake-up）；若实测有结构性变化必须在 baseline 文档解释清楚
- 写入新文档 `docs/benchmark/v161-bucket-budget-impact.md`，记录五维 R@5 + wake-up 输出在 N 个真实项目上的桶分布
