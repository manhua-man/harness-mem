# wake Specification

## Purpose

Wake renders confirmed project memory for an agent at task start. v2.1 起用户入口是
IDE command / Skill / Agent 自然语言（例如 `/hm:wake` 或“用 harness-mem 唤醒当前项目”），背后调用 MCP `wake` 或 shared wake renderer；CLI 不暴露日常 `wake` 子命令。

## Requirements

### Requirement: wake-up 按 memory_type 分桶预算

Wake renderer MUST 按 `memory_type` 把 `MemoryEntry` 候选分到三个桶：
`semantic / episodic / procedural`。每个桶 MUST 有独立配额；超过名额的 entry
在桶内按 importance + recency 截断。默认配额：
`semantic=0.5 / episodic=0.5 / procedural=0.0`。

#### Scenario: 默认配额下 semantic 与 episodic 各占一半

```text
Agent calls MCP wake(project_name="demo")
# Memory Entries  (source: structured_memory, 5 entries, ~480 chars)
#  bucket quotas: semantic=0.50 episodic=0.50 procedural=0.00
#  bucket fill:   semantic=2/2 episodic=3/2 procedural=0/0
- [convention/semantic] use single quote ...
- [observation/episodic] auth failure trace ...
[truncated within bucket: episodic 3/8]
```

### Requirement: procedural bucket default is zero

当 `bucket_quota_procedural = 0.0` 时，`procedural` 类型 entry MUST NOT 被选入
默认 wake 输出。procedural skills 通过显式 `search_skills` 使用；未来若引入 skill
hints，也必须是 opt-in compact hints，而不是默认注入完整 skill body。

#### Scenario: procedural entry not selected by default

```text
Given semantic=1, episodic=1, procedural=1 entries
When wake uses default quotas
Then procedural entry is not included in the default memory entries section
```

### Requirement: wake header 输出配额比例与填充率

Wake output MUST disclose bucket quota and fill information in the `# Memory Entries`
section. The `# Memory Entries` 段在 `(...chars)` 行下追加两行：

- `#  bucket quotas: semantic=<s> episodic=<e> procedural=<p>`
- `#  bucket fill:   semantic=<used>/<quota_count> episodic=... procedural=...`

#### Scenario: 桶内截断显式标注

```text
[truncated within bucket: episodic 3/8]
```

### Requirement: bucket_quota_enabled 显式可关

The runtime MUST support explicit disabling of bucket selection. Config
`[wake] bucket_quota_enabled = false` or equivalent runtime parameter MUST
restore the single-pool selection behavior.
This is a renderer/runtime option, not a daily CLI command.

#### Scenario: disabled bucket quota suppresses bucket header

```text
Agent calls MCP wake(project_name="demo", bucket_quota_enabled=false)
# Memory Entries  (source: structured_memory, 5 entries, ~480 chars)
- [convention/semantic] ...
- [observation/episodic] ...
```

Output MUST NOT contain `bucket quotas`, `bucket fill`, or bucket truncation markers.

### Requirement: 非法配额抛错并由 doctor 报告

The system MUST raise `WakeBucketQuotaError` for invalid wake bucket quota config.
当 `[wake] bucket_quota_*` 总和不在容差范围内或单值不在 `[0.0, 1.0]` 时，
加载该 config 的代码路径抛错；`harness-mem doctor` MUST 输出 `HM-101` 或
`HM-102` 并附修复指引。

#### Scenario: doctor 报告非法配额

```bash
$ harness-mem doctor
✗ wake bucket quotas
  code: HM-101 wake bucket quotas must sum to 1.0
  fix: edit ~/.harness-mem/config.toml [wake] bucket_quota_* (default: 0.5 / 0.5 / 0.0)
```
