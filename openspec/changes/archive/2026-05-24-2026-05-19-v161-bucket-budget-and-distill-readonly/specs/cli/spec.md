# cli

## Why

v1.6.1 在 CLI 上引入两条新参数（`wake --no-bucket-quota` 与 `search --memory-type`）+ 新 doctor 错误码（`HM-101 / HM-102`）+ distill 默认产 pending（兼容 flag `--auto-confirm`）。本 spec 写明 CLI 这一层的合同。

## ADDED Requirements

### Requirement: wake --no-bucket-quota 显式关闭分桶

CLI MUST 提供 `harness-mem wake --no-bucket-quota`，与 config `[wake] bucket_quota_enabled = false` 同义；CLI flag 优先于 config。关闭后 wake-up 行为 MUST 完全等价于 v1.6.0。

#### Scenario: --no-bucket-quota 抑制 bucket header
```bash
$ harness-mem wake --no-bucket-quota
# Memory Entries  (source: structured_memory, 5 entries, ~480 chars)
- [convention/semantic] ...
```
输出 MUST NOT 包含 `bucket quotas` / `bucket fill` 行。

### Requirement: search --memory-type 多值过滤

CLI MUST 接受 `harness-mem search "<query>" --memory-type <type>`，可重复传递多次实现多值 OR 过滤；非法 type 必须以非零退出码失败并提示有效集合。

#### Scenario: search --memory-type 单值
```bash
$ harness-mem search "single quote" --memory-type semantic
- mem_123 [convention/semantic] use single quote (score: 0.92)
```

#### Scenario: search --memory-type 多值
```bash
$ harness-mem search "auth" --memory-type semantic --memory-type episodic
```

### Requirement: distill --auto-confirm 兼容 flag

CLI MUST 接受 `harness-mem distill --auto-confirm`，把当次 distill 产出的 pending 候选整批转 `accepted`。该 flag MUST 在 `--help` 文本中标注 v1.6.1 之前的兼容路径。

#### Scenario: --auto-confirm 显式标注 accepted
```bash
$ harness-mem distill --auto-confirm
Distilling 3 sessions for demo...
  [convention/semantic] use single quote  (status: accepted)
```

#### Scenario: 默认行为产 pending
```bash
$ harness-mem distill
  [convention/semantic] use single quote  (status: pending)
```

### Requirement: doctor 登记 HM-101 / HM-102 错误码

`harness-mem doctor` MUST 在 `[wake]` config 段非法时输出：

- `HM-101 wake bucket quotas must sum to 1.0`：当 `bucket_quota_*` 总和不在 `[0.999, 1.001]`
- `HM-102 wake bucket quota out of range`：当任一 `bucket_quota_*` 不在 `[0.0, 1.0]`

修复指引 MUST 指向 `~/.harness-mem/config.toml` 的 `[wake]` 段，并提示默认值。`docs/error-codes.md` MUST 同步登记。

#### Scenario: doctor 报告 HM-101
```bash
$ harness-mem doctor
✗ wake bucket quotas
  code: HM-101 wake bucket quotas must sum to 1.0
  current: semantic=0.5 episodic=0.6 procedural=0.0 (sum=1.1)
  fix: edit ~/.harness-mem/config.toml [wake] bucket_quota_* (default: 0.5 / 0.5 / 0.0)
```
