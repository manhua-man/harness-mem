# cli Specification

## Purpose

CLI 是本地维护控制台。日常 AI 记忆工作（wake / search / ingest / candidate review / handoff 等）通过 IDE 命令、Skill 或 Agent 自然语言驱动 MCP 完成；CLI 只承担**安装、自检、显式 cleanup、本地维护**这类必须在终端执行的任务。

v2.1 起 CLI 子命令收敛为：`init` / `quickstart` (`qs`) / `doctor` / `import` / `purge` / `maintenance`。其他历史 CLI 子命令（`use`、`wake`、`search`、`ingest`、`status`、`profile`、`timeline`、`candidates`、`confirm`、`reject`、`correct`、`handoff` 等）已移除。日常等价行为请走 `mcp` 与 `daily-workflow` 规格。

## Requirements

### Requirement: 状态型命令统一格式

`harness-mem doctor` MUST 输出 Phase / Next step / Why 三段尾部格式，让用户知道当前阶段、下一步建议命令、原因。Next step 建议指向**当前 CLI 实际存在的子命令**或**用户可执行的 IDE 命令**，绝不引用已移除子命令。

接口: `quickstart`, `doctor`

#### Scenario: doctor 在 budget 高水位时给出 purge 建议

```text
$ harness-mem doctor
📍 Phase: Budget Warning (L3)
→ Next: harness-mem purge -p <project> --before <DATE> --category all --dry-run
   Why: Memory budget at 87%, archiving old observations can help
```

#### Scenario: doctor 在记忆已就绪时建议走 IDE 入口

```text
$ harness-mem doctor
📍 Phase: Ready
→ Next: 在 IDE 里运行 /hm:wake 或对 Agent 说 "用 harness-mem 唤醒当前项目"
   Why: Structured memory is ready, so wake-up is the shortest path back into project context.
```

### Requirement: structured purge 必须有明确项目上下文

当用户执行 `purge --category structured` 或 `purge --category all` 时，系统 MUST 具备明确的项目上下文；如果既没有 `--project` 也无法解析出活动项目（`active_project.txt`），命令 MUST 以非零退出码失败并提示用户显式给出项目。

#### Scenario: structured purge 缺少项目上下文

```bash
$ harness-mem purge --before 2026-01-01 --category all
Error: structured memory purge requires a project context. Use --project <name>, or set the active project from your IDE / Agent (e.g. 调用 set_active_project MCP 工具).
```

### Requirement: project-scoped purge

系统 MUST 支持 `harness-mem purge -p <project>`，并且在给定项目时只影响该项目的 structured memory。

#### Scenario: purge 只清理目标项目的 structured memory

```bash
$ harness-mem purge -p alpha --before 2026-01-01 --category all
Soft-deleted 12 observations for project 'alpha'.
Soft-deleted 3 structured memories for project 'alpha'.
```

### Requirement: next-step 提示应包含可执行项目上下文

当 `doctor` 提示用户通过 `purge` 采取行动时，系统 MUST 在建议命令里附带可执行的项目上下文（`-p <project>`），减少多项目环境下的歧义。

#### Scenario: doctor 给出带项目名的 purge 建议

```bash
Suggested action: harness-mem purge -p alpha --before 2026-01-01 --category all --dry-run
```

### Requirement: maintenance 命名空间下的 assign-memory-types 子命令

CLI MUST 提供 `harness-mem maintenance assign-memory-types`，参数语义如下：

- `--dry-run`（默认）：只打印待写入的 `(id, category, derived memory_type)` 与汇总，**不落盘**
- `--apply`：实际写入 `memory_type` 字段；与 `--dry-run` 互斥
- `--project <name>` / 活动项目：必须有项目上下文，否则命令必须以非零退出码失败并提示用户用 `--project` 或在 IDE/Agent 里设置 active project

命令 MUST 幂等：连续 `--apply` 后再次 `--dry-run` 显示 0 条待变更。

#### Scenario: dry-run 不写盘并显示待变更数

```bash
$ harness-mem maintenance assign-memory-types --dry-run
Would update 18 MemoryEntry rows (0 already typed).
- mem_123 (category=convention) -> semantic
- mem_456 (category=bug)        -> semantic
- mem_789 (category=raw_note)   -> episodic
No changes written. Use --apply to commit.
```

#### Scenario: apply 后再次 dry-run 显示 0 条

```bash
$ harness-mem maintenance assign-memory-types --apply
Updated 18 MemoryEntry rows.

$ harness-mem maintenance assign-memory-types --dry-run
Would update 0 MemoryEntry rows (18 already typed).
```

#### Scenario: 缺项目上下文时失败而非静默

```bash
$ harness-mem maintenance assign-memory-types --apply
Error: maintenance commands require a project context. Use --project <name>, or set the active project from your IDE / Agent.
```

### Requirement: import 子命令承担文件级离线导入

CLI `harness-mem import` MUST 支持把 AI Skill 在本地文件系统产出的 memory drafts 注入候选层。这是少数必须在终端执行的离线流程之一（agent 输出文件 → CLI 读取 → 候选层），不属于日常用户操作。

#### Scenario: import 把本地文件灌进候选层

```bash
$ harness-mem import --drafts ./tmp-drafts.jsonl --project alpha
Imported 7 draft memory entries into pending candidates for project 'alpha'.
```
