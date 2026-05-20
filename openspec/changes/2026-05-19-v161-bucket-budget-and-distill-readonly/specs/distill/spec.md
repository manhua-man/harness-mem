# distill

## Why

v1.6.0 的 distill 路径理论上可以直接调用 `ConfirmedRuleStore.delete / .update` 与 `RelationFactStore.delete / .update`——只是恰好没有这么做。一旦 v1.6.2 引入持久化向量后 distill 能"读全库 + 跑聚类"，写边界没锁死会被诱惑去"顺手清理一下"。本切片把"distill 写动作只能落候选层"通过 `DistillContext` 接口与单测做成静态边界。

## ADDED Requirements

### Requirement: DistillContext 只读读边界

系统 MUST 在 `harness_mem.distill_context.DistillContext` 暴露**唯一**的读路径接口给所有 distill adapter（`ClaudeCodeAdapter.distill_*`、`tools/session-distill`、`tools/mem-distill`）：

- `read_observations(...)`：读 verbatim
- `search(...)`：调 `read_api.search_memory`
- `list_confirmed_rules(...)`：读 confirmed rule snapshot
- `list_relation_facts(...)`：读 relation fact snapshot
- `compare(left, right)`：返回 `(left, right, diff_summary)`，不消费时间字段

`DistillContext` MUST NOT 暴露 `delete / update / purge` 类方法。

#### Scenario: DistillContext 没有任何 mutator 类方法
```python
>>> ctx = DistillContext(backend)
>>> [m for m in dir(ctx) if not m.startswith("_") and any(kw in m for kw in ("delete", "update", "purge", "mutate"))]
[]
```

### Requirement: distill 写动作只能落候选层

distill 路径产生的 `MemoryEntry` MUST 通过 `DistillContext.suggest_memory_entry(...)` 写入；这个方法 MUST 强制 `status="pending"`。distill 产生的 `RelationFact` MUST 通过 `DistillContext.suggest_relation_fact(...)` 写入，`status="pending"`。`RuleCandidate` 沿用既有候选层。

任何 distill adapter MUST NOT 接收 `LocalMemoryBackend` 实例本身——它的接口契约 MUST 是 `DistillContext`。这避免 adapter 内部"刚好绕过 suggest_*" 的退路。

#### Scenario: distill 默认产生 pending 候选
```bash
$ harness-mem distill
Distilling 3 sessions for demo...
  [convention/semantic] use single quote  (status: pending)
  [bug/semantic] trailing comma breaks parser  (status: pending)
Extracted 2 memory entries (pending) from 3 sessions
```

#### Scenario: --auto-confirm 转为 accepted（兼容旧 dogfood 流）
```bash
$ harness-mem distill --auto-confirm
Distilling 3 sessions for demo...
  [convention/semantic] use single quote  (status: accepted)
Extracted 2 memory entries (accepted) from 3 sessions
```

### Requirement: 越界尝试 raise DistillReadOnlyError

当 distill adapter（或 monkeypatch 测试）尝试通过 `DistillContext.__getattr__` 访问 `delete / update / purge` 类方法时，系统 MUST 抛 `DistillReadOnlyError(method, hint)`，hint MUST 指向相应的 `suggest_*` 入口。

#### Scenario: 直接拿 DistillContext 调 delete 方法 raise
```python
>>> ctx.delete_memory_entry("mem_123")
DistillReadOnlyError: delete_memory_entry is not allowed from distill context.
Use DistillContext.suggest_memory_entry(...) to propose changes via the candidate layer.
```

### Requirement: distill `--auto-confirm` flag 仅作兼容路径

CLI MUST 接受 `harness-mem distill --auto-confirm`，把当次 distill 产出的 pending 候选**整批**转 `accepted`，状态变化记入 `events.log`。该 flag 是 v1.6.1 的兼容入口，**不是**默认路径，CHANGELOG MUST 显式标注 v1.6.1 起 distill 默认产 pending。

#### Scenario: events.log 记录 auto-confirm 状态变化
```python
>>> events = read_events_log()
>>> [e for e in events if e["type"] == "MEMORY_DISTILLED" and e["extra"].get("auto_confirm")]
[{"project_name": "demo", "memory_entries": 2, "auto_confirm": True, ...}]
```
