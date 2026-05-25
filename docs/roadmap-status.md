# Roadmap Status

> 最后核对：2026-05-24，基于当前 repo 文件、实现模块与测试状态。
> 版本真值以 `pyproject.toml` + `harness_mem.__version__` 为准。

本文回答一个问题：哪些 roadmap 切片真的完成了，哪些只是 vision，哪些明确不做。
详细设计仍放在各版本 roadmap 文档里；本页只记录当前实现真值和边界。

## 当前版本

| 来源 | 值 |
|---|---|
| `pyproject.toml` | `2.1.0` |
| `harness_mem/__init__.py` | `2.1.0` |
| `CHANGELOG.md` | 已有 `2.1.0` 段 |

v2.1 成立的原因：当前树已经改变产品 surface。CLI 退回 maintenance-only，
REST API 已移除，文档明确 MCP 是 IDE command / Skill / Agent workflow 背后的隐藏传输层。

## 完成矩阵

| 切片 | 状态 | Repo 证据 | 边界 / caveat |
|---|---|---|---|
| v1.5.x | 已完成历史基础 | `docs/roadmap-v15x.md`、`CHANGELOG.md` v1.5.x 段 | 历史 CLI/REST 文案描述的是 pre-v2.1 surface；当前日常入口不再是 CLI。 |
| v1.6.0 | 已完成 | `MemoryEntry.memory_type`、LongMemEval per-type 文档和测试 | 加了分型与报告；本身不改变 wake selection。 |
| v1.6.1 | 已完成 | `wake_selection.py`、bucket budget config/tests、`DistillContext` readonly tests、`memory_type` filter tests | Bucket budget 可关闭；distill 写动作只进候选层。 |
| v1.6.2 | runtime 已完成 | persistent vector storage/tests、`maintenance rebuild-vector-index`、vector doctor checks、embedding shootout docs | 手动 benchmark gate 另行记录；默认模型保持 `all-MiniLM-L6-v2`。 |
| v1.7.0-v1.7.3 | 已完成 | temporal fields、current/history reads、supersede candidate loop、bounded `trace_relations`、`search_raw`、temporal/verbatim tests | Relation graph 引擎存在，但自然 session 自动填充仍稀疏，需要 LLM-driven distill 或显式 relation suggestion 喂数据。 |
| v1.8.0 | 已完成保守闭环 | `ProceduralCandidate`、confirmed `Skill`、`search_skills`、`record_skill_result`、MCP skill tools、procedural tests/fixtures | 不是 autonomous learning：Skill 不进默认 wake、不自动确认、不跨项目共享，也没有 daemon。 |
| v2.0.0 | 已完成 | heuristic `distill` CLI 与 MCP `distill_sessions` 已移除；distill 只走 LLM agent | `/hm:distill` 仍是用户工作流，背后走 `prepare_session_distill` + `suggest_*`。 |
| v2.1.0 | 当前 working tree | CLI parser 只暴露 maintenance 命令；REST package/tests 删除；README/AGENTS/OpenSpec 已围绕 Slash/Skill/Agent workflow 重写 | breaking surface cleanup；MCP tool signatures 与 data schema 保持稳定。 |

## 未完成 / 不做项

这些条目不要冒充已发布：

| 条目 | 当前状态 | 规划归宿 |
|---|---|---|
| 后台 daemon / IDE hook / turn-end 自检“随手记” | 未实现。当前候选写入只发生在显式 distill 或用户明确要求流程中。 | v2.4.2 可做显式 host-triggered reflection；always-on daemon 仍是 non-goal。 |
| 跨项目 Skill sharing | 未实现。v1.8 Skill 是 project-scoped。 | v2.4.0 |
| Procedural Skill 默认进入 wake | 未实现，且当前设计是显式 `search_skills`。 | v2.4.1 可做 compact opt-in skill hints；完整默认注入仍是 non-goal。 |
| AI 自治删除或改写 truth | 未实现，也不应该做。Truth 变化走 candidate / supersede / review。 | 永不做；只走 candidate/supersede/review。 |
| REST API 作为产品入口 | v2.1 已移除。 | 不规划恢复。 |
| CLI 日常工作流（`wake`、`search`、`timeline`、candidate review） | v2.1 已从 CLI surface 移除。日常使用走 IDE command / Skill / Agent workflow，背后由 MCP 支撑。 | 不规划恢复。 |
| v1.9 Memory Metabolism / Dream | 旧 vision 已删除，不再作为独立路线。 | 已拆成 v2.3 Memory Metabolism foundations 与 v2.4 controlled skill activation/sharing。 |

## 后续 Roadmap

| 切片 | 主题 | 文档 |
|---|---|---|
| v2.2.x | AI IDE 入口闭环：`/hm:distill`、`/hm:wake`、`/hm:search`、跨客户端测试、auto-review UX | `docs/roadmap-v22x.md` |
| v2.3.x | Memory Metabolism foundations：signals、replay windows、merge/stale suggestions、structure synthesis | `docs/roadmap-v23-v24.md` |
| v2.4.x | 跨项目 Skill sharing、compact opt-in skill hints、显式 host-triggered reflection | `docs/roadmap-v23-v24.md` |

## 短结论

v1.8 已完成，但完成的是保守 procedural-skill loop，不是后台自学习或自动随手记。
当前版本最好标为 v2.1，因为 v2.0 之后的主变化是产品 surface 清理：
CLI maintenance-only、REST removed、日常路径回到 `/hm:distill`、`/hm:wake`、
`/hm:search`、Skill 和自然语言 Agent 指令。

下一步应先做 v2.2，而不是直接跳 v2.3/v2.4。原因是：用户可见 AI IDE 闭环必须先稳定，
否则更深的 metabolism 只会产生更多用户难以触达和审核的候选量。
