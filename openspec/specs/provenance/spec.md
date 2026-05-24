# provenance Specification

## Purpose

定义 provenance（来源追溯）字段在 schema 与 wake / observation 读取路径上的契约。Provenance 是 harness-mem"可审计"承诺的实现支柱：每条 confirmed 记忆都能回到原始 observation / session。

## Requirements

### Requirement: provenance 字段

系统 MUST 为 `MemoryEntry`、`ConfirmedRule`、`TaskHandoff` 提供 provenance 字段。

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

### Requirement: get_observations 暴露来源摘要

MCP `get_observations` MUST 返回 observation 的 source session 与 timestamp，让 Agent 能在 UI 里展示来源。这条契约替代历史 CLI `harness-mem show -o <id>` 的能力。

#### Scenario: Agent 取一条 observation 的来源

```json
MCP -> get_observations({
  "project_name": "demo",
  "session_id": "sess_456"
})
Response: {
  "observations": [
    {
      "id": "obs_123",
      "content": "User prefers dark mode for code reviews",
      "source_session": "sess_456",
      "timestamp": "2026-04-20T10:00:00Z"
    }
  ]
}
```

### Requirement: wake-up 来源线索

`wake` MCP 工具 MUST 在输出里展示每条 rule / handoff 的来源线索。

#### Scenario: wake 显示规则来源

```text
Agent 调 wake(project_name="demo")
→ 返回 output 含:

  Memory Rules:
  1. User prefers dark mode [...truncated]
     📍 Source: obs_123, confirmed in session sess_456

  Pending Handoffs:
  1. Review dark mode implementation
     📍 Source: created in session sess_789
```
