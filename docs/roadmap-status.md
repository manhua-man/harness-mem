# Roadmap Status

> 最后核对：2026-05-30，基于当前 repo 文件、实现模块、OpenSpec 状态与测试状态。
> 版本真值以 `pyproject.toml` + `harness_mem.__version__` 为准。

本文回答一个问题：哪些 roadmap 切片真的完成了，哪些只是 vision，哪些明确不做。
详细设计仍放在各版本 roadmap 文档里；本页只记录当前实现真值和边界。

## 当前版本

| 来源 | 值 |
|---|---|
| `pyproject.toml` | `2.4.3` |
| `harness_mem/__init__.py` | `2.4.3` |
| `CHANGELOG.md` | 已有 `2.4.3` 段 |

当前收口基线是 v2.4.3：v2.4.0–v2.4.3 的 host-triggered reflection 全线（job model、
host 入口契约、queue health/doctor、维护 CLI）已实现、验证并发版。日常用户入口仍保持
v2.2 契约：Slash / Skill / 自然语言优先，CLI 仍是 maintenance console。

> **v2.4 发版状态（2026-05-30）**：版本号已从 `2.3.1` bump 到 `2.4.3`，`CHANGELOG.md`
> 已收口 v2.4.0–v2.4.3 发版段。v2.4 默认 `triggers.* = off`，不改变现有 wake/search
> 行为，也不启用 always-on daemon。

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
| v2.3.1 | 已完成 | `MergeSuggestionCandidate`、`StaleTruthSuggestionCandidate`、`metabolism_run` MCP tool、weak-link signal opt-in、token trim、calibration tests | 生成 reviewable suggestions；默认不改变 wake/search 行为，`weak_link_signals` 需 opt-in。 |
| v2.4.0 | 已完成（v2.4.3 收口发版） | `ReflectionJob` schema / 状态机、processing lease、provenance（`user\|agent\|ide_hook\|scheduler`）、retry policy、job list/read MCP helper、`test_reflection_*.py`（121）、`test_mcp_reflection_jobs.py`（10） | host-triggered reflection 的 job 生命周期地基；不引入常驻 worker；不暴露 `harness-mem reflection` 业务子命令。 |
| v2.4.1 | 已完成（v2.4.3 收口发版） | `harness_mem/config/`（errors + `load_merged_config` + `MergedConfig`）、`harness_mem/host_entry/`（argparse + 输出契约 + exit codes）、`test_config_errors.py`、`test_load_merged_config.py`（27）、`test_host_entry_*.py`（90+，含 contract / default-off / interruption / smoke） | host 入口只走 `python -m harness_mem.host_entry`，集成测试断言 hook 模板不出现 `harness-mem` 可执行调用；config `off` 时零 job/candidate 副作用。 |
| v2.4.2 | 已完成（v2.4.3 收口发版） | doctor queue / stale candidate / signal freshness / chronic failures checks、maintenance hints、结构化 health summary、`test_doctor_queue_health.py`、`test_candidate_health.py`、`test_signal_freshness.py`、`test_chronic_failures.py`、`test_maintenance_hints.py`、`test_health_summary.py` | 只读健康报告；不自动修复、不改 truth。 |
| v2.4.3 | 当前收口基线 | `config get/set/list/validate`、`integration install-cursor-hook` / `install-claude-hook`、`harness_mem/config/writer.py`（tomli_w）、`harness_mem/integration/`（模板 + installer + 边界自检）、`docs/cli/v2.4.md`、hook 边界契约测试 + scope guard（127 全绿） | 维护子命令只读/写 toml；生成的 hook 仅嵌入 `python -m harness_mem.host_entry --source ide_hook`，从不调 `harness-mem` 控制台脚本；CLI 维持 maintenance-only。 |

## 未完成 / 不做项

这些条目不要冒充已发布：

| 条目 | 当前状态 | 规划归宿 |
|---|---|---|
| 后台 daemon / IDE hook / turn-end 自检“随手记” | host 触发链路代码已完成（v2.4.0–v2.4.3，待发版）：`triggers.* = off` 默认；opt-in 时 hook 用 `python -m harness_mem.host_entry` 调业务命令，不调 `harness-mem` CLI。仍**无** always-on daemon（`worker.mode=daemon` 须 opt-in 且无 CLI 安装器）。 | v2.4 已交付 opt-in 安全触发；默认行为不变（off）。见 `docs/roadmap-v24.md`。 |
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

v2.4 reflection queue 四个切片（v2.4.0–v2.4.3）已实现、验证并发版（当前基线 v2.4.3）。
v2.4 默认 `triggers.* = off`，不改变现有 wake/search 行为，也不启用 always-on daemon。

优先级依据是：没有 signals 就无法 replay；没有 queue health 就无法安全 reflection；
没有 context assembly，更多 memory / skill 只会变成可搜索对象而不是真正可控的 agent memory。
