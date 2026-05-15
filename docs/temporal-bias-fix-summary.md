# Temporal Bias 修复总结

> **结论：已验证无价值，功能已于 2026-05-12 移除。本文档保留作为决策证据。**

> 日期：2026-05-12  
> 版本：v1.4.1  
> 状态：已修复，等待 benchmark 验证

---

## 问题发现

### 初始 Benchmark 结果

运行 `--compare-temporal-bias` 后发现：
- **所有 500 个问题的检索结果完全相同**
- Baseline vs Temporal delta = 0.0（所有题型）
- temporal-reasoning 题型无任何改善

### 根因分析

**原实现（`hybrid_search.py:240-250`）：**

```python
def _ranking_key(self, item, candidate_by_id, table, temporal_bias):
    row_id, score = item
    if not temporal_bias:
        return score, 0.0
    return score, self._temporal_sort_value(candidate_by_id[row_id], table)
```

**问题：**
1. temporal bias 仅作为**第二排序键**（tie-breaker）
2. 只在 RRF 分数**完全相同**时生效
3. RRF 分数是浮点数，几乎不会完全相同
4. 结果：500 个问题中，**0 次触发 temporal bias**

---

## 修复方案

### 实现：分数量化（方案 A）

**修改后的实现：**

```python
def _ranking_key(self, item, candidate_by_id, table, temporal_bias):
    row_id, score = item
    if not temporal_bias:
        return (-score, 0.0)
    # Quantize score to 0.01 precision to create tie situations
    quantized_score = round(score, 2)
    temporal_value = self._temporal_sort_value(candidate_by_id[row_id], table)
    return (-quantized_score, -temporal_value)
```

**关键变化：**
1. 量化分数到 0.01 精度（1%）
2. 使用负号实现降序排序（移除 `reverse=True`）
3. 在量化后的同分情况下，temporal bias 生效

**设计权衡：**
- ✅ 保持相关性优先（分数差异 > 0.01 时仍按相关性排序）
- ✅ 在相近分数时启用时间偏好
- ✅ 向后兼容，不改变 API
- ⚠️ 量化精度 0.01 是超参数，可能需要调优

---

## 验证过程

### 1. 单元测试更新

修改 `test_temporal_bias_is_opt_in_tie_breaker`：

```python
# 旧断言（假设分数完全相同）
assert biased_result.rows[0]["_hybrid_score"] == biased_result.rows[1]["_hybrid_score"]

# 新断言（验证量化后相同）
score_0 = biased_result.rows[0]["_hybrid_score"]
score_1 = biased_result.rows[1]["_hybrid_score"]
assert round(score_0, 2) == round(score_1, 2)
```

**结果：** ✅ 测试通过

### 2. Hybrid Search 测试套件

```bash
python -m pytest tests/search/test_hybrid_search.py -v
```

**结果：** ✅ 3/3 passed

### 3. 完整 Benchmark（进行中）

```bash
python -m harness_mem.tools.longmemeval \
  longmemeval_s_cleaned.json \
  --mode hybrid \
  --use-real-hybrid \
  --compare-temporal-bias \
  --out benchmarks/results/results_harness_hybrid_temporal_compare_top5_20260512_fixed.json
```

**预期：**
- Baseline vs Temporal 结果应该**不同**
- temporal-reasoning 题型应该有可测量的 delta（正或负）
- 可以根据 delta 决定是否默认启用

---

## 下一步

### 如果 Benchmark 显示正向影响（delta > 0）

1. ✅ 标记为 PASS
2. 运行 `daily-wake-temporal-safety` gate
3. Dogfooding 2 周
4. 考虑在 v1.4.2 默认启用

### 如果 Benchmark 显示无影响或负面影响（delta ≤ 0）

1. ❌ 标记为 FAIL
2. **移除 temporal bias 功能**
   - 删除 `--temporal-bias` 参数
   - 简化 `_ranking_key` 逻辑
   - 更新文档
3. 记录"已验证无价值"
4. V2 如需时间因素，考虑方案 B（时间衰减权重）

---

## 经验教训

### 1. Benchmark 的局限性

- Delta = 0 可能意味着"功能正确但无影响"
- 也可能意味着"功能根本没有执行"
- 需要额外验证机制（如检查结果是否真的不同）

### 2. Tie-breaker 的陷阱

- 浮点数几乎不会完全相同
- Tie-breaker 作为第二排序键，触发概率极低
- 需要主动制造"同分"情况（如量化）

### 3. 测试的重要性

- 单元测试假设了"分数完全相同"，但没有验证这个假设
- 应该测试"功能是否真的生效"，而不仅仅是"代码是否运行"

---

## 相关文件

- 修复实现：[harness_mem/search/hybrid_search.py](../harness_mem/search/hybrid_search.py)
- 测试更新：[tests/search/test_hybrid_search.py](../tests/search/test_hybrid_search.py)
- 完整分析：[temporal-bias-analysis.md](temporal-bias-analysis.md)
- Roadmap：[roadmap-v13-v14-proposal.md](roadmap-v13-v14-proposal.md)
