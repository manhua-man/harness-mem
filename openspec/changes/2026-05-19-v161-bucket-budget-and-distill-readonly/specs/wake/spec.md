# wake

## Why

v1.6.0 已经给 `MemoryEntry` 加了 `memory_type`，但 wake-up 还是单池 importance + recency 选 top-5；高价值的 confirmed rule（`semantic`）会被海量 episodic observation 挤出预算。v1.6.1 引入按 `memory_type` 的三桶预算，把"输出可控"做到位，给 v1.6.2 的 sqlite-vec 持久化向量留出可对比的基线。

## ADDED Requirements

### Requirement: wake-up 按 memory_type 分桶预算

`harness-mem wake` MUST 按 `memory_type` 把 `MemoryEntry` 候选分到三个桶：`semantic / episodic / procedural`。每个桶 MUST 有独立的名额配额（数量上限 = `floor(limit * quota)`）；超过名额的 entry 在桶内按 importance + recency 截断。**默认配额**：`semantic=0.5 / episodic=0.5 / procedural=0.0`。

#### Scenario: 默认配额下 semantic 与 episodic 各占一半
```bash
$ harness-mem wake
# Memory Entries  (source: structured_memory, 5 entries, ~480 chars)
#  bucket quotas: semantic=0.50 episodic=0.50 procedural=0.00
#  bucket fill:   semantic=2/2 episodic=3/2 procedural=0/0
- [convention/semantic] use single quote ...
- [bug/semantic] trailing comma breaks parser ...
- [observation/episodic] auth failure trace ...
[truncated within bucket: episodic 3/8]
```

#### Scenario: procedural 桶配额为 0 时不分配名额
当 `bucket_quota_procedural = 0.0` 时，`procedural` 类型的 entry MUST NOT 被选入 wake 输出（即使 importance score 极高），其名额按 `semantic > episodic > procedural` 优先级让给非空桶。

#### Scenario: 桶让渡补名额
当 `semantic` 桶候选不足（例如只有 1 条但配额是 2），未消费的名额 MUST 让给 `episodic`，反之亦然。让渡 MUST NOT 启用 `procedural` 桶（除非用户在 config 里把它的 quota 调高）。

### Requirement: wake header 输出配额比例与填充率

`harness-mem wake` 的 `# Memory Entries` 段 MUST 在 `(...chars)` 行下追加两行：

- `#  bucket quotas: semantic=<s> episodic=<e> procedural=<p>`，三位浮点对齐
- `#  bucket fill:   semantic=<used>/<quota_count> episodic=... procedural=...`

`fill` 行的 `quota_count` 是配额让渡前的**原始**名额（即 `floor(limit * quota)`），`used` 是实际填充数。

#### Scenario: 桶内截断显式标注
```bash
[truncated within bucket: episodic 3/8]
```
当 `episodic` 桶候选数 8 但分配名额 3 时，wake 输出 MUST 在该桶最后一条 entry 之后追加该截断行。

### Requirement: bucket_quota_enabled 显式可关

CLI MUST 提供 `harness-mem wake --no-bucket-quota`，与 config `[wake] bucket_quota_enabled = false` 同义；CLI flag 优先于 config。关闭后 wake-up 行为 MUST 完全等价于 v1.6.0（全库混排 top-k）。

#### Scenario: --no-bucket-quota 退回 v1.6.0 行为
```bash
$ harness-mem wake --no-bucket-quota
# Memory Entries  (source: structured_memory, 5 entries, ~480 chars)
- [convention/semantic] ...
- [observation/episodic] ...
- ...
```
关闭分桶时 MUST NOT 输出 `bucket quotas` / `bucket fill` 行与桶截断标注。

### Requirement: 非法配额抛错并由 doctor 报告

当 `[wake] bucket_quota_*` 的总和不在 `[0.999, 1.001]` 容差或单值不在 `[0.0, 1.0]` 时，加载该 config 的代码路径 MUST 抛 `WakeBucketQuotaError`；`harness-mem doctor` MUST 输出 `code: HM-101 wake bucket quotas must sum to 1.0` 或 `code: HM-102 wake bucket quota out of range`，并附 `~/.harness-mem/config.toml` 修复指引。

#### Scenario: doctor 报告非法配额
```bash
$ harness-mem doctor
✗ wake bucket quotas
  code: HM-101 wake bucket quotas must sum to 1.0
  current: semantic=0.5 episodic=0.6 procedural=0.0 (sum=1.1)
  fix: edit ~/.harness-mem/config.toml [wake] bucket_quota_* (default: 0.5 / 0.5 / 0.0)
```
