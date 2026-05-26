# Roadmap Status

> 最后核对：2026-05-27，基于当前 repo 文件、实现模块、OpenSpec 状态与测试状态。
> 版本真值以 `pyproject.toml` + `harness_mem.__version__` 为准。

本文回答一个问题：哪些 roadmap 切片真的完成了，哪些只是 vision，哪些明确不做。
详细设计仍放在各版本 roadmap 文档里；本页只记录当前实现真值和边界。

## 当前版本

| 来源 | 值 |
|---|---|
| `pyproject.toml` | `2.3.1` |
| `harness_mem/__init__.py` | `2.3.1` |
| `CHANGELOG.md` | 已有 `2.3.1` 段 |

当前收口基线是 v2.3.1：v2.3.0 signals / replay 已发布，v2.3.1 metabolism suggestion pass
已完成实现与验证。日常用户入口仍保持 v2.2 契约：Slash / Skill / 自然语言优先，
CLI 仍是 maintenance console。

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
| v2.1.0 | 已完成 | CLI parser 只暴露 maintenance 命令；REST package/tests 删除；README/AGENTS/OpenSpec 已围绕 Slash/Skill/Agent workflow 重写 | breaking surface cleanup；MCP tool signatures 与 data schema 保持稳定。 |
| v2.2.0 | 已完成 | `plugins/harness-mem/commands/hm/*.md`、`plugins/harness-mem/skills/harness-mem/SKILL.md`、`docs/v2-user-test-packet.md`、loop harness tests | 用户入口稳定为 Slash / Skill / 自然语言；CLI 仍是 maintenance console；无后台 daemon。 |
| v2.3.0 | 已完成 | `RetrievalSignal`、`MetabolismRun`、replay window selector、`metabolism_preview` MCP tool、OpenSpec `metabolism` spec | 只读 preview / signal 地基；不写 suggestion、不改 truth。 |
| v2.3.1 | 当前收口基线 | `MergeSuggestionCandidate`、`StaleTruthSuggestionCandidate`、`metabolism_run` MCP tool、weak-link signal opt-in、token trim、calibration tests | 生成 reviewable suggestions；默认不改变 wake/search 行为，`weak_link_signals` 需 opt-in。 |

## 未完成 / 不做项

这些条目不要冒充已发布：

| 条目 | 当前状态 | 规划归宿 |
|---|---|---|
| 后台 daemon / IDE hook / turn-end 自检“随手记” | 未实现。当前候选写入只发生在显式 distill 或用户明确要求流程中。 | v2.4：默认 off；opt-in 时 hook 用 `python -m` 调业务命令（不用 `harness-mem` CLI）；见 `docs/roadmap-v24.md`。 |
| Context Assembly / File Context | 未实现。当前 wake 有 bucket 和 source，但还不是完整 Memory Stack renderer。 | v2.5 |
| Wiki Bridge / Compact Claim Index | 未实现。当前有 raw evidence 和 search_raw，但没有 generated knowledge cache / compact claim index。 | v2.6 |
| 自动 contradiction / stale / merge suggestion | 未实现。当前已有 supersede candidate 机制，但还没有 detector 主动发现冲突。 | v2.6 |
| 跨项目 Skill sharing | 未实现。v1.8 Skill 是 project-scoped。 | v2.7.0 |
| Procedural Skill 默认进入 wake | 未实现，且当前设计是显式 `search_skills`。 | v2.7.1 可做 compact opt-in skill hints；完整默认注入仍是 non-goal。 |
| AI 自治删除或改写 truth | 未实现，也不应该做。Truth 变化走 candidate / supersede / review。 | 永不做；只走 candidate/supersede/review。 |
| REST API 作为产品入口 | v2.1 已移除。 | 不规划恢复。 |
| CLI 日常工作流（`wake`、`search`、`timeline`、candidate review） | v2.1 已从 CLI surface 移除。日常使用走 IDE command / Skill / Agent workflow，背后由 MCP 支撑。 | 不规划恢复。 |
| v1.9 Memory Metabolism / Dream | 旧 vision 已删除，不再作为独立路线。 | 已拆成 v2.3 signals/replay、v2.4 reflection queue、v2.6 contradiction/metabolism suggestions。 |

## 后续 Roadmap

| 切片 | 主题 | 文档 |
|---|---|---|
| v2.2.x | AI IDE 入口闭环：`/hm:distill`、`/hm:wake`、`/hm:search`、跨客户端测试、auto-review UX | `docs/roadmap-v22x.md` |
| v2.3.x | Signals / Replay 地基：`RetrievalSignal`、`MetabolismRun`、replay window、`metabolism_preview` | `docs/roadmap-v23.md` |
| v2.4.x | Host-triggered Reflection + Queue Health：job lifecycle、config toml、维护子命令管配置、hook 仅业务命令、doctor | `docs/roadmap-v24.md` |
| v2.5.x | Context Assembly + File Context：Memory Stack renderer、file-context、分层 wake | `docs/roadmap-v25.md` |
| v2.6.x | Wiki Bridge + Compact Index + Contradiction：knowledge cache、claim index、stale/merge/supersede suggestions | `docs/roadmap-v26.md` |
| v2.7.x | Cross-Project Skills + Controlled Activation：shared skills、skill hints、skill improvement suggestions | `docs/roadmap-v27.md` |

## 短结论

v2.2 已完成用户入口闭环，但当前产品仍不是后台自学习或自动随手记。
后续路线已经按一个版本一个文档重切：先做 v2.3 signals/replay，
再做 v2.4 reflection queue，随后是 v2.5 context assembly、v2.6 wiki/contradiction，
最后再进入 v2.7 cross-project skill。

优先级依据是：没有 signals 就无法 replay；没有 queue health 就无法安全 reflection；
没有 context assembly，更多 memory / skill 只会变成可搜索对象而不是真正可控的 agent memory。
