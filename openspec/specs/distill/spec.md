# distill Specification

## Purpose

Distill 是 LLM-agent-driven workflow，不是 CLI heuristic extractor。v2.0 起
`harness-mem distill` CLI 与 MCP `distill_sessions` 已移除；当前用户入口是
`/hm:distill`、repo Skill、或自然语言请求，背后走 `prepare_session_distill`
与 `suggest_*` 候选写入工具。

## Requirements

### Requirement: DistillContext 只读边界

系统 MUST 在 `harness_mem.distill_context.DistillContext` 暴露只读与候选写入接口给 distill workflow：

- `read_observations(...)`
- `search(...)`
- `list_confirmed_rules(...)`
- `list_relation_facts(...)`
- `compare(left, right)`
- `suggest_memory_entry(...)`
- `suggest_relation_fact(...)`

`DistillContext` MUST NOT 暴露 `delete / update / purge` 类方法。

#### Scenario: DistillContext 没有任何 mutator 类方法

```python
>>> ctx = DistillContext(backend)
>>> [m for m in dir(ctx) if not m.startswith("_") and any(kw in m for kw in ("delete", "update", "purge", "mutate"))]
[]
```

### Requirement: distill 写动作只能落候选层

distill workflow 产生的 `MemoryEntry` / `RelationFact` / `RuleCandidate` MUST
先进入 candidate layer。任何影响 confirmed truth 的变化 MUST 通过 confirm/reject
或 supersede review 路径完成。

#### Scenario: agent distill writes pending candidates

```text
Agent runs /hm:distill
-> prepare_session_distill returns evidence packet
-> Agent calls suggest_memory_entry / suggest_rule
-> list_candidates shows new pending candidates
```

### Requirement: removed heuristic distill is unavailable

The system MUST reject removed heuristic distill entrypoints. It does not expose
`harness-mem distill` or MCP `distill_sessions`. If no LLM agent is available,
distill is unavailable rather than silently falling back to regex extraction.

#### Scenario: removed CLI distill fails

```text
$ harness-mem distill
harness-mem: error: argument command: invalid choice: 'distill'
```

#### Scenario: no heuristic fallback

```text
WHEN /hm:distill cannot obtain an evidence packet or LLM agent
THEN the agent reports a runtime/configuration problem
AND it does not call a regex fallback extractor
```

### Requirement: 越界尝试 raise DistillReadOnlyError

The system MUST raise `DistillReadOnlyError(method, hint)` when distill code
tries to access forbidden mutator methods. 当 distill adapter（或 monkeypatch 测试）
尝试通过 `DistillContext.__getattr__` 访问 `delete / update / purge` 类方法时，
hint MUST 指向相应的 `suggest_*` 入口。

#### Scenario: 直接拿 DistillContext 调 delete 方法 raise

```python
>>> ctx.delete_memory_entry("mem_123")
DistillReadOnlyError: delete_memory_entry is not allowed from distill context.
Use DistillContext.suggest_memory_entry(...) to propose changes via the candidate layer.
```
