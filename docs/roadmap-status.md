# Roadmap Status

> 最后核对：2026-06-03，基于当前 repo 文件、实现模块、OpenSpec 状态与测试状态。
> 版本真值以 `pyproject.toml` + `harness_mem.__version__` 为准。

本文回答一个问题：哪些 roadmap 切片真的完成了，哪些只是 vision，哪些明确不做。
详细设计仍放在各版本 roadmap 文档里；本页只记录当前实现真值和边界。

## 当前版本

| 来源 | 值 |
|---|---|
| `pyproject.toml` | `2.9.10` |
| `harness_mem/__init__.py` | `2.9.10` |
| `CHANGELOG.md` | 已有 `2.9.10` 段；`Unreleased` 当前为空 |

当前收口基线是 v2.9.10：v2.5.0–v2.5.2 的 context assembly / wake renderer /
file_context、v2.6.0–v2.6.3 的 knowledge cache / wiki bridge / contradiction
boundary、v2.7.0–v2.7.2 的 cross-project procedural skill 能力，以及
v2.8.0–v2.8.2 的 session-distill maintenance surfaces、v2.9.0 的 PRD sync
candidate surface、v2.9.1 的 status triage surface，以及 v2.9.2 的 plugin
doctor helper integrity、v2.9.3 的 CLI maintenance surface truth、v2.9.4 的 stale CLI surface guard sync、v2.9.5 的 shell completion maintenance truth、v2.9.6 的 maintenance surface collateral sync、v2.9.7 的 README and telemetry maintenance truth、v2.9.8 的 maintenance surface collateral guard、v2.9.9 的 reflection project-root resolution，以及 v2.9.10 的 worker-mode truth sync 都已落地。

> **v2.9.10 发版状态（2026-06-03）**：版本号已 bump 到 `2.9.10`。v2.9 在保持
> slash-first、candidate-before-truth、maintenance-only CLI 边界的前提下，
> 把 `/hm:prd-sync [--apply]`、`/hm:status` 与 repo-local plugin doctor helper
> 一起收束成显式、可验证的 maintenance / triage surfaces，并把主 CLI spec、
> stale-surface guardrail、shell completion、MCP/user-test collateral 与
> README/telemetry collateral guard 一起对齐到已经 shipped 的 `config` /
> `integration` 命名空间；同时把 `reflection_once(project_root=None)` 的缺省解析
> 收紧成 known-root-first、cwd-final-fallback，并清掉 `worker.mode` 的旧 daemon
> 这一类会误导当前 config loader 的旧口径。

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
| v2.4.3 | 已完成 | `config get/set/list/validate`、`integration install-cursor-hook` / `install-claude-hook`、`harness_mem/config/writer.py`（tomli_w）、`harness_mem/integration/`（模板 + installer + 边界自检）、`docs/cli/v2.4.md`、hook 边界契约测试 + scope guard（127 全绿） | 维护子命令只读/写 toml；生成的 hook 仅嵌入 `python -m harness_mem.host_entry --source ide_hook`，从不调 `harness-mem` 控制台脚本；CLI 维持 maintenance-only。 |
| v2.5.0 | 已完成（v2.5.1 收口发版） | `ContextAssemblyPlan` schema（`harness_mem/core/schemas/context_assembly_plan.py`：L0–L4、`PlanEntry` 带 source_ids/why_included/summary/truth_status、`Budget`、`TruncationAccounting`、L4 `DrilldownPointer`）、side-effect-free `assemble_context_plan(...)`（`harness_mem/context_assembly.py`）、`tests/test_context_assembly_*.py` | 只读 planning artifact；组装于既有读面之上，不改 `wake`/`search` 输出、不写存储、不发 `RetrievalSignal`。 |
| v2.5.1 | 已完成 | 纯函数渲染模块 `harness_mem/commands/wake_render.py`（`render_wake_plan` + helpers，无 I/O）、计划驱动的 `cmd_wake_up`、`tests/test_wake_render_*.py` / `tests/integration/test_wake_render_side_effects.py` / `tests/mcp/test_wake_render_stdout.py`（pytest 956 passed） | cold-start `wake` 由 plan 驱动分层渲染 L0/L1/L2，每条带 source id + `📍`；L1/L2 只渲染 `confirmed_current`。旧扁平格式（Confirmed Rules / Relation Facts / Memory Entries / bucket-quota / weak-link 子标题 / 使用徽章）被取代；relation facts/skill hints 归 L3 query-driven。schema/assembler 未改动；既有信号+touch、MCP stdout 纯净性保留；未引入 `file_context`（v2.5.2）。 |
| v2.5.2 | 已完成并并入 v2.6.0 | `harness_mem/core/schemas/file_context.py`、`harness_mem/file_context.py`、MCP `file_context` tool（`harness_mem/mcp/server.py` + `harness_mem/mcp/tool_specs.py`）、`tests/test_file_context.py` / `tests/test_file_context_readonly.py` / `tests/mcp/test_file_context_stdout.py` / `tests/mcp/test_smoke.py` | advisory-only helper：不拦截读文件、不发 `RetrievalSignal`、不 bump usage / last_accessed、skill 只给 hint、结果包含 `cost_hint` 与 `stale_file_signal`。 |
| v2.6.0 | 已完成 | `harness_mem/knowledge_cache.py`、`ProjectProfile.curated_doc_paths`、doctor knowledge-cache block、`maintenance prepare-knowledge-cache` / `cleanup-generated-cache`、`tests/test_knowledge_cache.py`、`tests/cli/test_knowledge_cache_cli.py`、OpenSpec `v260-knowledge-cache-boundary` | 只做 boundary / visibility / source hash / cleanup；不编译 wiki、不让 generated cache 进入 wake/search truth。 |
| v2.6.1 | 已完成 | `rebuild_wiki_bridge(...)`、`knowledge-cache/generated/claims.json` / `topics.json` / `entities.json`、`maintenance rebuild-wiki-bridge`、doctor generated counts、OpenSpec `v261-wiki-bridge-compact-index` | 编译 accepted memory / confirmed rules / relation facts / curated docs 到 generated wiki bridge；claim 带 source drilldown，但 generated outputs 不进默认 truth surface。 |
| v2.6.2 | 已完成 | `list_candidates` 返回 `MergeSuggestionCandidate` / `StaleTruthSuggestionCandidate`、`merge_suggestion_count` / `stale_truth_suggestion_count`、`_propose_supersedes(...)`、OpenSpec `v262-candidate-review-surface-and-contradiction-boundary` | merge/stale/supersede suggestion 只进入 candidate/review surface；不会自动 confirm、不会直接 mutate truth。 |
| v2.6.3 | 已完成 | MCP `wake(renderer="compact")`、`load_compact_wake_payload(...)`、`render_compact_wake_payload(...)`、OpenSpec `v263-compact-wake-renderer`、compact renderer tests | compact renderer 是 opt-in generated summary；默认 `wake` 不变，generated-only 内容仍不进入默认 `search_memory`。 |
| v2.7.0 | 已完成 | shared `Skill.scope` model、`origin_project` / `source_ids` / portability metadata、`skill_promotion` candidate、explicit shared `search_skills`、activation warnings、separate project/shared feedback、OpenSpec `v270-cross-project-skill-library` | shared skill 只能 reviewed promotion；默认 wake / skill search 仍 project-scoped。 |
| v2.7.1 | 已完成 | MCP `wake(include_skill_hints=...)`、`skill_hint_limit`、MCP `get_skill`、OpenSpec `v271-controlled-skill-activation` | skill hint 是 opt-in compact surface；默认 wake 不注入完整 procedural body。 |
| v2.7.2 | 已完成 | `skill_revision_suggestion` / `skill_deprecation_suggestion` candidates、`detect_skill_improvements` / `confirm_skill_revision` / `reject_skill_revision`、`detect_skill_deprecations` / `confirm_skill_deprecation` / `reject_skill_deprecation`、OpenSpec `v272-skill-improvement-suggestions` | 改进与退役都走 review；confirmed skill 不自动改写，shared skill 不静默退役。 |
| v2.8.0 | 已完成 | `/hm:mark` closure guardrails、`validate_distilled_guardrails(...)`、`/hm:prune --statuses distilled,skipped --source-missing` boundary、OpenSpec `v280-session-distill-maintenance-surfaces` | session closure 和 manifest cleanup 正式进入版本线；不碰 canonical truth。 |
| v2.8.1 | 已完成 | `/hm:review-kb` baseline state（`reviewed_at` / `total_entries` / `summary`）、`stable/needs-review/stale/superseded` status model、`/hm:prune-kb` backup-first and stale/superseded confinement、OpenSpec `v281-knowledge-base-review-and-prune` | knowledge-base audit 与 cleanup 正式进入版本线；dry-run 不写 backup、不改文件。 |
| v2.8.2 | 当前收口基线 | `/hm:verify-entry` targeted recheck、KB growth reminder、packet overlap reminder、note overlap reminder、OpenSpec `v282-targeted-verification-and-reminder-surfaces` | targeted review 与 reminder 只做 summary-level nudges；不会自动 prune、auto-supersede 或阻断 distill。 |
| v2.9.0 | 已完成 | `/hm:prd-sync [--apply]`、projectless maintenance boundary、`prd-distilled/*.md` candidate output、OpenSpec `v290-prd-sync-candidate-surface`、`test_prd_sync_*` | PRD sync 只读 bundled packets，默认 dry-run；`--apply` 只写 candidate markdown，不直改 PRD/roadmap 或 confirmed truth。 |
| v2.9.1 | 已完成 | `/hm:status` triage contract、MCP `get_project_status` `phase/suggested_slash/reason/repair_hint`、OpenSpec `v291-status-triage-surface`、`test_get_project_status_*` | status 是 read-only triage 入口；pending candidates 只作为 repair-only `/hm:review` hint，不升格成主 happy path。 |
| v2.9.2 | 已完成 | `plugins/harness-mem/scripts/doctor.ps1` repair、hint-only `-Wake`、OpenSpec `v292-plugin-doctor-helper-integrity`、script smoke test | repo-local plugin doctor helper 只调用维护 CLI surface；不再触发 `invalid choice: 'status'`。 |
| v2.9.3 | 已完成 | `openspec/specs/cli/spec.md` top-level command sync、`config` / `integration` namespace contract、OpenSpec `v293-cli-maintenance-surface-truth` | 主 CLI spec 现在与真实 `harness-mem --help` 一致，明确 `config` / `integration` 属于 maintenance-only surface。 |
| v2.9.4 | 已完成 | `tests/test_stale_cli_surface.py` allowlist sync、OpenSpec `v294-stale-cli-surface-guard-sync` | focused stale-CLI guard 现在与当前 maintenance surface 一致，不会把 `config` / `integration` 视为过时口径。 |
| v2.9.5 | 已完成 | `harness_mem/shell_completion.py` sync、OpenSpec `v295-shell-completion-maintenance-truth`、`tests/test_shell_completion.py` | shell completion 现在与当前 maintenance surface 一致，不再漏掉 `config` / `integration` / `qs`。 |
| v2.9.6 | 已完成 | `openspec/specs/mcp/spec.md` sync、`docs/v2-user-test-packet.md` sync、OpenSpec `v296-maintenance-surface-collateral-sync` | MCP 主 spec 与用户测试包现在都承认 `config` / `integration` 属于当前维护 CLI surface。 |
| v2.9.7 | 已完成 | `README.md` maintenance summary sync、`openspec/specs/telemetry/spec.md` sync、OpenSpec `v297-maintenance-surface-readme-and-telemetry-sync` | README 与 telemetry 主 spec 现在都承认 `config` / `integration` 属于当前维护 CLI surface。 |
| v2.9.8 | 当前收口基线 | `tests/test_maintenance_surface_collateral.py`、OpenSpec `v298-maintenance-surface-collateral-guard` | maintenance-surface collateral 现在有 focused regression guard，不再只靠人工回读。 |
| v2.9.9 | 已完成 | `harness_mem/commands/reflection_jobs.py` known-root-first resolution、`tests/test_reflection_once_integration.py` 两个缺省 root 覆盖、OpenSpec `v299-reflection-project-root-resolution` | 只收紧共享 reflection business command 的缺省 `project_root` 解析；`host_entry` 仍优先传显式 `--project-root`。 |
| v2.9.10 | 当前版本 | `docs/roadmap-v24.md` / `docs/cli/v2.4.md` / `docs/roadmap-status.md` worker-mode truth sync、`tests/test_worker_mode_truth.py`、OpenSpec `v2910-worker-mode-truth-sync` | `worker.mode` 当前真值已锁定为 `off/on` gate；不代表 shipped always-on daemon。 |

## 未完成 / 不做项

这些条目不要冒充已发布：

| 条目 | 当前状态 | 规划归宿 |
|---|---|---|
| 后台 daemon / IDE hook / turn-end 自检“随手记” | host 触发链路代码已完成（v2.4.0–v2.4.3）并已发版：`triggers.* = off` 默认；opt-in 时 hook 用 `python -m harness_mem.host_entry` 调业务命令，不调 `harness-mem` CLI。仍**无** always-on daemon（`worker.mode` 当前只有 `off/on` gate，且无 CLI 安装器或默认后台路径）。 | v2.4 已交付 opt-in 安全触发；默认行为不变（off）。见 `docs/roadmap-v24.md`。 |
| Context Assembly / File Context | 已完成并并入正式版本线。 | 见 `docs/roadmap-v25.md`。 |
| Wiki Bridge / Compact Claim Index / Compact Renderer | 已完成到 v2.6.3 范围：generated wiki bridge、claim/topic/entity index、opt-in compact wake renderer。 | 见 `docs/roadmap-v26.md`。 |
| 自动 contradiction / stale / merge suggestion | v2.6.2 已完成 candidate-only review surface 和 supersede proposer；仍不做自动 apply / autonomous truth mutation。 | 后续若扩展，只能继续走 candidate/review 边界。 |
| 跨项目 Skill 默认静默注入 | 未实现，也不计划做。shared skill 已实现，但必须通过显式 shared search / opt-in hint surface 消费。 | 已由 v2.7.x 定义为 non-goal。 |
| Procedural Skill 默认进入 wake | 未实现；当前只支持 opt-in compact skill hints，完整 body 仍需显式 `get_skill`。 | 已由 v2.7.1 定义为 non-goal。 |
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
| v2.8.x | Session-Distill Maintenance Surfaces：`/hm:mark`、`/hm:prune`、`/hm:review-kb`、`/hm:prune-kb`、`/hm:verify-entry` 的正式版本线 | `docs/roadmap-v28.md` |
| v2.9.x | PRD Sync Candidate Surface：`/hm:prd-sync` 默认 dry-run、`--apply` 只写 candidate markdown、不直改 PRD/roadmap | `docs/roadmap-v29.md` |

## 短结论

v2.2 已完成用户入口闭环，但当前产品仍不是后台自学习或自动随手记。
路线已经按一个版本一个文档重切并完成到 v2.8：v2.3 signals/replay、
v2.4 reflection queue、v2.5 context assembly、v2.6 wiki/contradiction、
v2.7 cross-project skill，以及 v2.8 session-distill maintenance 都已落地。

v2.4 reflection queue 四个切片（v2.4.0–v2.4.3）已实现、验证并发版。
v2.5 context assembly 与 file context、v2.6 knowledge cache / wiki /
candidate-only contradiction boundary、v2.7 shared skill / controlled
activation / reviewed improvement suggestions，以及 v2.8 session-distill
maintenance surfaces 都已并入正式版本线。当前仍未启用 always-on daemon，
MCP stdout 纯净性继续保持，shared skill 也仍然坚持显式消费。

优先级依据是：没有 signals 就无法 replay；没有 queue health 就无法安全 reflection；
没有 context assembly，更多 memory / skill 只会变成可搜索对象而不是真正可控的 agent memory。

