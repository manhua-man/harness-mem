# provenance Specification

## Purpose
TBD - created by archiving change v1x-retention-stability-reset. Update Purpose after archive.
## Requirements
### Requirement: provenance 字段

系统 MUST 为 MemoryEntry、ConfirmedRule、TaskHandoff 增加 provenance 字段。

接口: MemoryEntry, ConfirmedRule, TaskHandoff

```python
@dataclass
class MemoryEntry:
    id: str
    content: str
    provenance: Optional[Provenance] = None

@dataclass
class Provenance:
    source_observation_id: Optional[str] = None
    source_session_id: Optional[str] = None
    source_summary: Optional[str] = None
    created_at: datetime
```

#### Scenario: 创建带 provenance 的 memory entry
```python
>>> entry = MemoryEntry(
...     id="mem_001",
...     content="User prefers dark mode",
...     provenance=Provenance(
...         source_observation_id="obs_123",
...         source_session_id="sess_456",
...         source_summary="User mentioned this during code review"
...     )
... )
```

### Requirement: show 来源追溯

系统 SHALL 支持 show 能追溯到来源摘要与 session。

接口: `harness-mem show -o <observation-id>`

#### Scenario: 查看 observation 来源
```
$ harness-mem show -o obs_123
=== Observation ===
ID: obs_123
Content: User prefers dark mode for code reviews

💡 Source: from session sess_456 (2026-04-20)
   "User prefers dark mode"
```

### Requirement: wake-up 来源线索

系统 SHALL 在 wake-up 中展示 rule / handoff 的来源线索。

接口: wake 命令输出

#### Scenario: wake 显示规则来源
```
$ harness-mem wake
Memory Rules:
1. User prefers dark mode [...truncated]
   💡 Source: obs_123, confirmed in session sess_456

Pending Handoffs:
1. Review dark mode implementation
   💡 Source: created in session sess_789
```

