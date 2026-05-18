# evaluation

## Why

v1.5.x 的优化主路径暴露了一个测量盲点：LongMemEval 平均 R@5 是单一数字，没有按维度切片。`v1.5.2` 一度想用调 RRF 权重提升总分，最后是诊断脚本告诉我们瓶颈在 FTS 召回。v1.6.x 不能再依赖直觉调参——必须把 LongMemEval 的五个维度（multi-session / temporal-reasoning / single-session-* / knowledge-update / abstention-style）作为一等公民评分指标。

## ADDED Requirements

### Requirement: LongMemEval 五维评分作为一等公民输出

`harness_mem.tools.longmemeval` MUST 在 CLI 输出与 JSON 报告中同时给出每个 question type 的 R@K：CLI 输出 `PER-TYPE RECALL` 段按维度名字典序对齐；JSON 报告必须包含顶层 `per_type: {question_type: avg_recall}` 字段。

#### Scenario: CLI 输出五维段
```text
$ python -m harness_mem.tools.longmemeval ds.json --mode hybrid --top-k 5

  AVG RECALL: 0.953

  PER-TYPE RECALL:
    knowledge-update              R@5=1.000  (n=78)
    multi-session                 R@5=0.923  (n=132)
    single-session-assistant      R@5=0.982  (n=56)
    single-session-preference     R@5=0.967  (n=30)
    single-session-user           R@5=1.000  (n=87)
    temporal-reasoning            R@5=0.915  (n=117)
```

#### Scenario: JSON 报告含 per_type 字段
```json
{
  "avg_recall": 0.953,
  "per_type": {
    "multi-session": 0.923,
    "temporal-reasoning": 0.915,
    "single-session-user": 1.000,
    "single-session-preference": 0.967,
    "single-session-assistant": 0.982,
    "knowledge-update": 1.000
  }
}
```

### Requirement: 登记的 question_type 集合与未知维度告警

系统 MUST 维护一个登记的 `question_type` 集合，至少包含：`multi-session`、`temporal-reasoning`、`single-session-user`、`single-session-preference`、`single-session-assistant`、`knowledge-update`。当数据集出现未登记的 `question_type` 时，系统 MUST 通过 `warnings.warn(...)` 提示，但 MUST NOT 阻断评测继续。

#### Scenario: 已登记维度不告警
```python
>>> run_eval(dataset_with_only_known_types)
# 不产生 warning
```

#### Scenario: 未知维度产生 warning
```python
>>> run_eval(dataset_with_question_type="abstention-style-v2")
UserWarning: Unknown question_type 'abstention-style-v2' encountered; this dimension will be reported but not part of the registered set.
```

### Requirement: baseline 文档作为 v1.6.x 评估锚点

仓库 MUST 在 `docs/benchmark/v160-baseline.md` 记录 v1.6.0 启动当日跑出的五维 R@5 baseline，覆盖至少 `fts` 与 `hybrid` 两种 mode。后续切片（v1.6.1 / v1.6.2）的"不回退"承诺 MUST 引用该 baseline。

#### Scenario: baseline 文档结构
```markdown
# v1.6.0 LongMemEval baseline

| mode  | avg_recall | multi-session | temporal-reasoning | single-session-user | ... |
|-------|------------|---------------|--------------------|---------------------|-----|
| fts   | 0.876      | 0.840         | 0.812              | 0.987               | ... |
| hybrid| 0.953      | 0.923         | 0.915              | 1.000               | ... |
```
