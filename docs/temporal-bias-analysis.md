# Temporal Bias Benchmark 分析报告

> **结论：已验证无价值，功能已于 2026-05-12 移除。本文档保留作为决策证据。**

> 生成日期：2026-05-12  
> 基线版本：v1.4.1  
> 数据集：LongMemEval (500 questions)

---

## 执行摘要

**目标：** 量化 temporal bias 对 hybrid search 各题型的影响，决定是否应默认启用。

**方法：** 运行两次完整 LongMemEval benchmark：
- Baseline: `--use-real-hybrid` (temporal_bias=False)
- Temporal: `--use-real-hybrid --temporal-bias` (temporal_bias=True)

**决策标准：**
1. 整体 R@5 不能下降（avg_recall delta ≥ 0）
2. temporal-reasoning 题型 R@5 必须提升（delta > 0）
3. 其他题型不能显著退化（delta ≥ -0.02）

---

## Benchmark 结果

### 修复前（原始实现）

| 指标 | Baseline | Temporal | Delta | 判断 |
|------|----------|----------|-------|------|
| Avg R@5 | 0.9418 | 0.9418 | **0.0** | ⚠️ 功能未生效 |

**问题：** 500/500 个问题的检索结果完全相同，temporal bias 完全未触发。

---

### 修复后（分数量化）

#### 整体指标

| 指标 | Baseline | Temporal | Delta | 判断 |
|------|----------|----------|-------|------|
| Avg R@5 | 0.9418 | 0.9352 | **-0.0066** | ❌ **整体下降** |
| 完美召回率 (1.0) | 88.6% | 87.6% | -1.0pp | 下降 |
| 零召回率 (0.0) | 2.0% | 2.4% | +0.4pp | 恶化 |

#### 分题型结果

| 题型 | Baseline R@5 | Temporal R@5 | Delta | 判断 |
|------|--------------|--------------|-------|------|
| single-session-user | 0.9857 | 0.9714 | **-0.0143** | ❌ 下降 |
| single-session-assistant | 0.9821 | 0.9821 | 0.0 | 持平 |
| single-session-preference | 0.9000 | 0.9333 | **+0.0333** | ✅ 唯一提升 |
| multi-session | 0.9096 | 0.8957 | **-0.0139** | ❌ 下降 |
| temporal-reasoning | 0.9093 | 0.8982 | **-0.0110** | ❌ **目标题型下降** |
| knowledge-update | 1.0000 | 1.0000 | 0.0 | 持平 |

**关键发现：**
1. ✅ Temporal bias 修复后**确实生效**（结果不再完全相同）
2. ❌ 但效果是**负面的**：整体召回率下降 0.66pp
3. ❌ **temporal-reasoning 题型下降 1.1pp**（本应提升的目标题型）
4. ❌ 5/6 题型下降或持平，仅 single-session-preference 提升

---

## 决策门判断

根据 `_temporal_bias_gate` 逻辑：

```json
{
  "search_default_candidate": false,
  "decision": "keep-disabled",
  "reason": "overall recall regressed",
  "requires_wake_benchmark": true
}
```

### 决策路径

- [ ] **PASS**: avg_recall delta ≥ 0 且 temporal-reasoning delta > 0  
  → 候选默认启用，需 wake benchmark 验证
  
- [x] **FAIL**: avg_recall delta < 0  
  → **保持禁用，整体召回退化**
  
- [x] **FAIL**: temporal-reasoning delta ≤ 0  
  → **保持禁用，目标题型无改善**

### 失败原因分析

**为什么 temporal bias 降低了召回率？**

1. **时间偏好与相关性冲突**  
   - 在量化后的同分情况下，temporal bias 优先选择最近的结果
   - 但最近的结果不一定是最相关的
   - 例如：用户询问早期项目决策，但最近有无关讨论

2. **量化精度过粗**  
   - 0.01 精度（1%）可能过粗，导致相关性差异被抹平
   - 原本相关性略高的旧记忆被最近的低相关记忆替代

3. **temporal-reasoning 题型的反直觉结果**  
   - 预期：时间偏好应该帮助"最近发生了什么"类问题
   - 实际：这类问题往往需要**特定时间点**的记忆，而非"最近"
   - 例如："上周二我说了什么"需要精确时间，而非最近的对话

---

## 根因分析

### 为什么 temporal bias 完全未生效？

**当前实现（`hybrid_search.py:240-250`）：**

```python
def _ranking_key(self, item, candidate_by_id, table, temporal_bias):
    row_id, score = item
    if not temporal_bias:
        return score, 0.0
    return score, self._temporal_sort_value(candidate_by_id[row_id], table)
```

**问题：** temporal bias 仅作为**第二排序键**（tie-breaker），只在 RRF 分数**完全相同**时生效。

**实际情况：** RRF 分数是浮点数，几乎不会出现完全相同的情况：
- RRF 公式：`score = 1/(k + fts_rank) + vec_weight/(k + vec_rank)`
- 即使两个文档的 FTS 排名相同，向量排名也几乎不可能相同
- 结果：500 个问题中，**0 次触发 temporal bias**

### 设计缺陷

1. **误解了"同分"的含义**  
   - 原设计假设：RRF 会产生大量同分结果
   - 实际情况：RRF 分数几乎总是唯一的

2. **temporal bias 的作用被完全架空**  
   - 作为 tie-breaker 时，永远不会被使用
   - 用户启用 `--temporal-bias` 后，行为与不启用完全相同

3. **benchmark 无法验证功能是否工作**  
   - Delta = 0 可能意味着"功能正确但无影响"
   - 也可能意味着"功能根本没有执行"（实际情况）

---

## 修复方案

### 方案 A：分数量化 + Tie-breaking（推荐）

**思路：** 将 RRF 分数量化到固定精度（如 0.001），人为制造"同分"情况。

```python
def _ranking_key(self, item, candidate_by_id, table, temporal_bias):
    row_id, score = item
    if not temporal_bias:
        return (-score, 0.0)  # 负号用于降序排序
    
    # 量化分数到 0.001 精度，制造同分情况
    quantized_score = round(score, 3)
    temporal_value = self._temporal_sort_value(candidate_by_id[row_id], table)
    return (-quantized_score, -temporal_value)
```

**优点：**
- 保持相关性优先（分数差异 > 0.001 时仍按相关性排序）
- 在相近分数时启用时间偏好
- 向后兼容，不改变 API

**缺点：**
- 量化精度是超参数，需要调优
- 仍然是 tie-breaker，影响范围有限

---

### 方案 B：时间衰减权重（更激进）

**思路：** 直接将时间因素融入分数计算，而非作为 tie-breaker。

```python
def _apply_temporal_boost(self, score, timestamp, table):
    """Apply time-based boost to relevance score."""
    if timestamp is None:
        return score
    
    # 计算时间衰减：最近 30 天内的记忆获得 boost
    days_old = (datetime.now() - timestamp).days
    if days_old < 30:
        boost = 1.0 + (30 - days_old) / 30 * 0.2  # 最多 +20%
        return score * boost
    return score
```

**优点：**
- 真正影响排序，不依赖同分
- 可配置衰减曲线和 boost 强度

**缺点：**
- 可能降低旧但高度相关记忆的排名
- 需要更多 benchmark 验证
- 行为变化更大，风险更高

---

### 方案 C：仅对 temporal-reasoning 题型启用（保守）

**思路：** 根据 query 特征判断是否需要时间偏好。

```python
def _should_use_temporal_bias(self, query: str) -> bool:
    """Detect if query is asking about temporal ordering."""
    temporal_keywords = [
        "recent", "latest", "last", "previous", "earlier", 
        "before", "after", "first", "most recent", "updated"
    ]
    return any(kw in query.lower() for kw in temporal_keywords)
```

**优点：**
- 只在明确需要时间信息的查询中启用
- 降低误伤风险

**缺点：**
- 启发式规则不可靠
- 需要维护关键词列表
- 仍然没有解决 tie-breaker 不生效的问题

---

### 推荐决策

**短期（v1.4.1）：** 采用**方案 A（分数量化）**，量化精度设为 `0.01`（1%）。

**理由：**
1. 最小改动，风险可控
2. 可以立即验证 temporal bias 是否真的有用
3. 如果 benchmark 仍然 delta=0，说明即使生效也无影响，可以放心移除

**中期（v1.4.2 或 V2）：** 根据方案 A 的 benchmark 结果决定：
- 如果有正向影响 → 考虑方案 B（时间衰减）
- 如果仍无影响 → 移除 temporal bias 功能，简化代码

---

## 风险分析

### 已知风险

1. **旧但相关的记忆被降权**  
   - 场景：用户询问早期项目决策，但最近有无关讨论
   - 缓解：temporal bias 仅在**同分**时生效，不改变相关性排序

2. **最近噪音记忆被提升**  
   - 场景：最近有大量低质量 observation
   - 缓解：需配合 memory quality scoring (v1.4.2)

3. **wake-up 预算被最近内容占满**  
   - 场景：重要旧规则被挤出 wake-up context
   - 缓解：已有 importance protection (usage_count 保护)

### 需要 Wake Benchmark 验证的问题

- [ ] 重要旧 memory 是否被最近普通 memory 挤出？
- [ ] usage_count 保护是否足够？
- [ ] 是否需要引入 memory decay 机制？

---

## 下一步行动

### 立即行动（v1.4.1）

**结论：移除 temporal bias 功能**

基于 benchmark 证据，temporal bias 在当前设计下：
1. ❌ 降低整体召回率（-0.66pp）
2. ❌ 降低目标题型 temporal-reasoning 召回率（-1.1pp）
3. ❌ 仅在 1/6 题型中有正向影响
4. ❌ 已验证无价值

**执行步骤：**

1. **回滚代码修改**
   - 恢复 `hybrid_search.py:_ranking_key` 到修复前版本
   - 移除分数量化逻辑
   - 恢复 `reverse=True` 排序

2. **移除 temporal bias 参数**
   - CLI: 删除 `--temporal-bias` 参数
   - MCP: 删除 `search_memory.temporal_bias` 参数
   - REST API: 删除 `/search?temporal_bias=true` 支持

3. **清理代码**
   - 删除 `HybridSearchLayer.__init__` 的 `temporal_bias` 参数
   - 删除 `_temporal_sort_value` 方法（如果仅用于此功能）
   - 简化 `_ranking_key` 逻辑

4. **更新文档**
   - 标记 temporal bias 为"已验证无价值"
   - 更新 roadmap 状态
   - 保留 benchmark 结果作为证据

5. **更新测试**
   - 删除 `test_temporal_bias_is_opt_in_tie_breaker`
   - 或标记为 skip 并注释原因

### 如果未来需要时间因素（V2）

考虑**方案 B：时间衰减权重**，但需要：
1. 更精细的衰减曲线设计
2. 可配置的 boost 强度
3. 针对特定查询类型启用（而非全局）
4. 更全面的 benchmark 验证

### 不推荐的方案

- ❌ 调整量化精度（0.01 → 0.001）：治标不治本
- ❌ 仅对 temporal-reasoning 启用：该题型反而下降最多
- ❌ 继续优化当前设计：根本问题是时间偏好与相关性冲突

---

## 附录：原始数据

### Baseline 运行日志

```
[待填充]
```

### Temporal 运行日志

```
[待填充]
```

### 对比 JSON

文件路径：`benchmarks/results/results_harness_hybrid_temporal_compare_top5_YYYYMMDD.json`

```json
[待填充]
```

---

## 参考文档

- [Roadmap v1.3/v1.4](roadmap-v13-v14-proposal.md) — Temporal Bias 规划
- [Benchmark System](benchmark_system.md) — 测试门与质量标准
- [HybridSearchLayer](../harness_mem/search/hybrid_search.py) — 实现细节
