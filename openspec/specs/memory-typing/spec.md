# memory-typing Specification

## Purpose

定义 `MemoryEntry.memory_type` 字段语义、老数据派生规则、以及 `harness-mem maintenance assign-memory-types` 这条 backfill 命令的契约。这是为 v1.6.1 wake-up bucket budget 与未来 v1.8 procedural skill 储备的 schema 字段。

## Requirements

### Requirement: MemoryEntry 显式记忆类型字段

`MemoryEntry` MUST 暴露 `memory_type: Literal["episodic", "semantic", "procedural"]` 字段，默认值 `semantic`。`to_dict` MUST 输出该字段，`from_dict` MUST 兼容缺失该字段的老数据。

#### Scenario: 新建 MemoryEntry 默认 memory_type 为 semantic

```python
>>> entry = MemoryEntry(project_name="demo", category="convention", content="use single quote", source="manual")
>>> entry.memory_type
'semantic'
```

#### Scenario: to_dict / from_dict 往返保留 memory_type

```python
>>> entry = MemoryEntry(project_name="demo", category="bug", content="x", source="manual", memory_type="episodic")
>>> MemoryEntry.from_dict(entry.to_dict()).memory_type
'episodic'
```

### Requirement: 老数据加载按 category 自动派生 memory_type

当 `MemoryEntry.from_dict` 收到的字典缺失 `memory_type` 字段时，系统 MUST 按 `category` 自动派生：

- `architecture | convention | api | bug | decision` -> `semantic`
- 上述以外的任何 category（含空 / unknown） -> `episodic`

派生 MUST NOT 修改原始 `category` 字段。

#### Scenario: 老 JSON blob 没有 memory_type 时按 category 派生

```python
>>> data = {"project_name": "demo", "category": "convention", "content": "use single quote", "source": "obs_1"}
>>> MemoryEntry.from_dict(data).memory_type
'semantic'
```

#### Scenario: 未知 category 派生为 episodic

```python
>>> data = {"project_name": "demo", "category": "raw_note", "content": "x", "source": "obs_1"}
>>> MemoryEntry.from_dict(data).memory_type
'episodic'
```

### Requirement: procedural 类型保留但 v1.6.0 不被产生

系统 MUST 接受 `memory_type="procedural"` 的字面量与读写，但 v1.6.0 的 distill / ingest / 自动派生路径 MUST NOT 主动产生 `procedural` 类型的 `MemoryEntry`。`procedural` 字段的实际填充路径属于 v1.8（`Skill` / `ProceduralCandidate`）。

#### Scenario: 显式构造 procedural 记忆受支持

```python
>>> entry = MemoryEntry(project_name="demo", category="decision", content="x", source="manual", memory_type="procedural")
>>> entry.memory_type
'procedural'
```

#### Scenario: 自动派生不会产生 procedural

```python
>>> any(MemoryEntry.from_dict({...}).memory_type == "procedural" for _ in derived_from_category)
False
```

### Requirement: 一次性幂等 backfill 命令

系统 MUST 提供 `harness-mem maintenance assign-memory-types` 命令，对已存在 `MemoryEntry` 一次性 backfill `memory_type`：默认 `--dry-run`，需要显式 `--apply` 才落盘；连续运行 `--apply` 后再次 `--dry-run` 必须显示 0 条待变更。

#### Scenario: dry-run 不写盘

```bash
$ harness-mem maintenance assign-memory-types --dry-run
Would update 18 MemoryEntry rows (0 skipped already typed).
No changes written. Use --apply to commit.
```

#### Scenario: apply 后幂等

```bash
$ harness-mem maintenance assign-memory-types --apply
Updated 18 MemoryEntry rows.

$ harness-mem maintenance assign-memory-types --dry-run
Would update 0 MemoryEntry rows (18 already typed).
```

#### Scenario: 缺活动项目时明确失败

```bash
$ harness-mem maintenance assign-memory-types --apply
Error: maintenance commands require a project context. Use --project <name>, or set the active project from your IDE / Agent.
```
