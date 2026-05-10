# v1x-retention-stability-reset Design

## 设计原则

1. **local-first**: 所有数据留在本地，不引入外部向量 DB
2. **渐进式退化**: embedding 不可用时自动退化到纯 FTS
3. **最小抽象**: 当 DevEx 想加抽象、Linus 想砍抽象时，选能消除当前重复和耦合的最小抽象
4. **CLI/MCP 一致性**: 同一概念和生命周期在两端保持一致

## purge 软删除设计

### 实现方式

```python
# 不做物理删除，只做标记
class CompactionMarker(Enum):
    SOFT_DELETED = "soft_deleted"
    COMPACTED = "compacted"

# 查询时自动过滤
def query_with_compaction_filter(query):
    return query.where(CompactionMarker != SOFT_DELETED)
```

### CLI 接口

```
harness-mem purge --before 2026-01-01 --category observations --dry-run
harness-mem purge --before 2026-01-01 --category observations
harness-mem purge --before 2026-01-01 --category all
```

### doctor/wake 集成

当 budget 显示 L3/L4+ 时，自动建议：

```
⚠️  Memory budget at 87% (L4)
💡 Run: harness-mem purge --before 2026-03-01 --category observations --dry-run
   to see what can be archived.
```

## HybridSearchLayer 设计

### 架构

```
┌─────────────────────────────────────┐
│          HybridSearchLayer          │
├─────────────────────────────────────┤
│ mode: auto | fts | hybrid          │
│ - auto: 根据 embedding 可用性选择     │
│ - fts: 纯 SQLite FTS               │
│ - hybrid: fts + vector 融合         │
└─────────────────────────────────────┘
         │              │
         ▼              ▼
┌─────────────┐  ┌──────────────────┐
│ SQLite FTS  │  │ Local Embedding  │
│ (always)    │  │ (lazy load)      │
└─────────────┘  └──────────────────┘
```

### 懒加载策略

```python
class HybridSearchLayer:
    _embedding_model = None

    @property
    def embedding_model(self):
        if self._embedding_model is None:
            try:
                self._embedding_model = load_embedding_model()
            except ImportError:
                self._embedding_model = False  # marker for "not available"
        return self._embedding_model

    def search(self, query, mode="auto"):
        if mode == "auto":
            if self.embedding_model:
                return self.hybrid_search(query)
            return self.fts_search(query)
        elif mode == "fts":
            return self.fts_search(query)
        elif mode == "hybrid":
            return self.hybrid_search(query)
```

## Provenance 设计

### 数据模型

```python
@dataclass
class Provenance:
    source_observation_id: Optional[str] = None
    source_session_id: Optional[str] = None
    source_summary: Optional[str] = None
    created_at: datetime

# MemoryEntry 增加 provenance 字段
class MemoryEntry:
    id: str
    content: str
    provenance: Optional[Provenance] = None
    compacted: Optional[CompactionMarker] = None
```

### 展示格式

```
$ harness-mem show -o obs_123

=== Observation ===
ID: obs_123
Content: User prefers dark mode...

💡 Source: from session sess_456 (2026-04-20)
   "User prefers dark mode for code reviews"
```

## Learning Loop 闭环设计

### MCP 流程

```
1. correct (user) → review → confirm/reject
                     ↑
                     └── suggest_rule (user提出建议)
```

### scope=project|all 设计

```python
# MCP 查询接口
async def search_memories(
    query: str,
    scope: Literal["project", "all"] = "project",
    project_name: Optional[str] = None  # required only when scope=project
):
```

## CLI 拆分设计

### 目标结构

```
commands/
├── __init__.py
├── quickstart.py
├── ingest.py
├── search.py
├── wake.py
├── doctor.py
├── status.py
├── profile.py
├── purge.py
├── correct.py
├── handoff.py
└── show.py
```

### 统一格式化器

```python
# formatters.py
def phase_formatter(phase: Phase, next_step: str, why: str) -> str:
    return f"""
📍 Phase: {phase.value}
→ Next: {next_step}
   Why: {why}
"""

def wake_budget_formatter(budget: WakeBudget) -> str:
    ...
```

## ingest cursor 设计

### 状态跟踪

```python
class IngestCursor:
    project_name: str
    last_session_id: str
    last_ingest_timestamp: datetime

# 增量 ingest 逻辑
def ingest_incremental(project: str, cursor: IngestCursor):
    new_sessions = get_sessions_since(cursor.last_session_id, cursor.last_ingest_timestamp)
    for session in new_sessions:
        process_session(session)
    cursor.update(new_sessions[-1])
```

### CLI 接口

```
harness-mem ingest           # 增量（默认）
harness-mem ingest --full-rescan  # 全量回退
```
