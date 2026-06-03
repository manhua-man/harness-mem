# Roadmap Status

> 最后核对：2026-06-04，基于当前 repo 文件、实现模块、OpenSpec 状态与测试状态。
> 版本真值以 `pyproject.toml` + `harness_mem.__version__` 为准。

本文回答一个问题：哪些 roadmap 切片真的完成了，哪些只是 vision，哪些明确不做。
详细设计仍放在各版本 roadmap 文档里；本页只记录当前实现真值和边界。

## 当前版本

| 来源 | 值 |
|---|---|
| `pyproject.toml` | `2.9.60` |
| `harness_mem/__init__.py` | `2.9.60` |
| `CHANGELOG.md` | 已有 `2.9.60` 段；`Unreleased` 当前为空 |

当前收口基线是 v2.9.60：v1.5 baseline、v1.6 persistent vectors / bucket budget、
v1.7 temporal truth、v1.8 procedural skill、v2.0 heuristic distill 移除、
v2.1 maintenance-only CLI、v2.2 用户入口闭环（runtime 已落地；OpenSpec `5.5`
手工 gate 已过，但 full matrix coverage 仍可继续扩展）、v2.3 signals/replay、v2.4
reflection queue、v2.5 context assembly / wake renderer / file_context、
v2.6 knowledge cache / wiki bridge / contradiction、v2.7 cross-project
procedural skill、v2.8 session-distill maintenance surfaces，以及
v2.9.0–v2.9.60 这一整条从 `/hm:prd-sync` 起步、随后扩成 maintenance / triage /
truth-sync 的 release train 都已落地。

> **v2.9.60 发版状态（2026-06-04）**：版本号已 bump 到 `2.9.60`。这一版继续补
> `v2-user-test-packet` 的正式 scenario evidence，但这次落在 repo-truth 可复核面：packet
> 定义的 `S11` 字符串扫描范围里，旧的 daily CLI 面现在只剩“已删除/不要求手动跑”的反例说明，
> 不再作为当前用户 path 被教学。也就是说，`README.md`、plugin README、`plugins/harness-mem/commands/hm/*.md`
> 这些高可见入口上，stale CLI surface 已经按 packet 定义范围收干净。剩下没补齐的仍是更强的
> live client scenarios，尤其是 `S4/S5/S7` 和 UI 级 cross-client pair。

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
| v2.2.0 | 已完成（OpenSpec `5.5` gate 已过） | `plugins/harness-mem/commands/hm/*.md`、`plugins/harness-mem/skills/harness-mem/SKILL.md`、`docs/v2-user-test-packet.md`、loop harness tests、OpenSpec archive `v220` tasks | 用户入口稳定为 Slash / Skill / 自然语言；loop harness 已覆盖 non-Claude parity，且 packet 现在已有 `2026-05-25` 的 Claude Code gate entry、`2026-06-03` 的 Codex + generic MCP 两条 non-Claude entry；generic MCP 还进一步补到了 live stdio 的 S8 / S9 evidence（`auto_review_candidates` preview/apply 与 `suggest_correction` one-shot supersede）；Cursor hook install 可生成，且本地 Cursor 证据已覆盖 hooks runtime、agent exec startup、`mcp-router` 连通与 harness-mem 工具 cache；当前机器还已出现真实的 Cursor agent run log（如 `search_memory` / `timeline` / `get_project_profile` 等 MCP 调用）。full 12-scenario cross-client matrix 仍未补齐，但按 OpenSpec archive `5.5` 的原始门槛，手工 release gate 已闭环；CLI 仍是 maintenance console；无后台 daemon。 |
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
| v2.8.2 | 已完成 | `/hm:verify-entry` targeted recheck、KB growth reminder、packet overlap reminder、note overlap reminder、OpenSpec `v282-targeted-verification-and-reminder-surfaces` | targeted review 与 reminder 只做 summary-level nudges；不会自动 prune、auto-supersede 或阻断 distill。 |
| v2.9.0 | 已完成 | `/hm:prd-sync [--apply]`、projectless maintenance boundary、`prd-distilled/*.md` candidate output、OpenSpec `v290-prd-sync-candidate-surface`、`test_prd_sync_*` | PRD sync 只读 bundled packets，默认 dry-run；`--apply` 只写 candidate markdown，不直改 PRD/roadmap 或 confirmed truth。 |
| v2.9.1 | 已完成 | `/hm:status` triage contract、MCP `get_project_status` `phase/suggested_slash/reason/repair_hint`、OpenSpec `v291-status-triage-surface`、`test_get_project_status_*` | status 是 read-only triage 入口；pending candidates 只作为 repair-only `/hm:review` hint，不升格成主 happy path。 |
| v2.9.2 | 已完成 | `plugins/harness-mem/scripts/doctor.ps1` repair、hint-only `-Wake`、OpenSpec `v292-plugin-doctor-helper-integrity`、script smoke test | repo-local plugin doctor helper 只调用维护 CLI surface；不再触发 `invalid choice: 'status'`。 |
| v2.9.3 | 已完成 | `openspec/specs/cli/spec.md` top-level command sync、`config` / `integration` namespace contract、OpenSpec `v293-cli-maintenance-surface-truth` | 主 CLI spec 现在与真实 `harness-mem --help` 一致，明确 `config` / `integration` 属于 maintenance-only surface。 |
| v2.9.4 | 已完成 | `tests/test_stale_cli_surface.py` allowlist sync、OpenSpec `v294-stale-cli-surface-guard-sync` | focused stale-CLI guard 现在与当前 maintenance surface 一致，不会把 `config` / `integration` 视为过时口径。 |
| v2.9.5 | 已完成 | `harness_mem/shell_completion.py` sync、OpenSpec `v295-shell-completion-maintenance-truth`、`tests/test_shell_completion.py` | shell completion 现在与当前 maintenance surface 一致，不再漏掉 `config` / `integration` / `qs`。 |
| v2.9.6 | 已完成 | `openspec/specs/mcp/spec.md` sync、`docs/v2-user-test-packet.md` sync、OpenSpec `v296-maintenance-surface-collateral-sync` | MCP 主 spec 与用户测试包现在都承认 `config` / `integration` 属于当前维护 CLI surface。 |
| v2.9.7 | 已完成 | `README.md` maintenance summary sync、`openspec/specs/telemetry/spec.md` sync、OpenSpec `v297-maintenance-surface-readme-and-telemetry-sync` | README 与 telemetry 主 spec 现在都承认 `config` / `integration` 属于当前维护 CLI surface。 |
| v2.9.8 | 已完成 | `tests/test_maintenance_surface_collateral.py`、OpenSpec `v298-maintenance-surface-collateral-guard` | maintenance-surface collateral 现在有 focused regression guard，不再只靠人工回读。 |
| v2.9.9 | 已完成 | `harness_mem/commands/reflection_jobs.py` known-root-first resolution、`tests/test_reflection_once_integration.py` 两个缺省 root 覆盖、OpenSpec `v299-reflection-project-root-resolution` | 只收紧共享 reflection business command 的缺省 `project_root` 解析；`host_entry` 仍优先传显式 `--project-root`。 |
| v2.9.10 | 已完成 | `docs/roadmap-v24.md` / `docs/cli/v2.4.md` / `docs/roadmap-status.md` worker-mode truth sync、`tests/test_worker_mode_truth.py`、OpenSpec `v2910-worker-mode-truth-sync` | `worker.mode` 当前真值已锁定为 `off/on` gate；不代表 shipped always-on daemon。 |
| v2.9.11 | 已完成 | `docs/roadmap-v24.md` / `docs/cli/v2.4.md` scheduler truth sync、`tests/test_worker_mode_truth.py` 扩展覆盖 scheduler、OpenSpec `v2911-scheduler-trigger-truth-sync` | `triggers.scheduler` 当前真值已锁定为 `off/on` gate；不代表 shipped cron expression schema。 |
| v2.9.12 | 已完成 | `docs/roadmap-v24.md` distill-mode truth sync、`tests/test_worker_mode_truth.py` 扩展覆盖 `distill.mode`、OpenSpec `v2912-distill-mode-truth-sync` | `distill.mode` 当前真值已锁定为 `defer_to_agent/inline/worker`；不代表 shipped inline LLM 或 always-on worker path。 |
| v2.9.13 | 已完成 | `docs/roadmap-v24.md` host-entry example sync、`tests/test_host_entry_module_truth.py`、OpenSpec `v2913-host-entry-module-truth-sync` | current-truth docs 现在只使用 `python -m harness_mem.host_entry --project-root ... --source ide_hook` 这一 shipped host-entry invocation；不再保留 `<host_entry>` placeholder、`harness_mem.host` 旧模块名或伪 `reflection_once` 子命令。 |
| v2.9.14 | 已完成 | `docs/roadmap-v24.md` config/job-model truth sync、`tests/test_v24_config_and_job_truth.py`、OpenSpec `v2914-v24-config-and-job-truth-sync` | current-truth docs 现在只把 `load_merged_config()` 描述成四个 recognized keys 的 merged loader，不再暗示 `project_name` / `active_project.txt`；queue model 也只描述 `ReflectionJob`，`review` 只是 phase。 |
| v2.9.15 | 已完成 | `plugins/harness-mem/commands/hm/wake.md`、`plugins/harness-mem/skills/harness-mem/SKILL.md`、`tests/test_wake_entrypoint_truth.py`、OpenSpec `v2915-wake-entrypoint-truth-sync` | repo-local wake guidance 现在默认走一等 MCP `wake` surface；compact/generated summary 与 skill hints 也通过 `wake(...)` 参数显式开启，不再默认手工拼低层 read tools。 |
| v2.9.16 | 已完成 | `docs/best-practices.md`、`tests/test_best_practices_wake_truth.py`、OpenSpec `v2916-best-practices-wake-truth-sync` | `best-practices` 现在把 `wake` 记为一等读取工具，并把 MCP `wake(project_name=<project>)` 写成默认 wake-up surface；compact / skill hints 仍是显式 opt-in。 |
| v2.9.17 | 已完成 | `plugins/harness-mem/commands/hm/distill.md`、`plugins/harness-mem/skills/harness-mem/SKILL.md`、`openspec/specs/mcp/spec.md`、`tests/test_distill_auto_review_truth.py`、OpenSpec `v2917-distill-auto-review-entrypoint-truth-sync` | `/hm:distill` 与 repo-local skill 现在默认走 `auto_review_candidates(project_name=<project>, apply=true)` 这条 shared review surface，不再把手工 per-item confirm/reject 写成 shipped distill 主路径。 |
| v2.9.18 | 已完成 | `plugins/harness-mem/commands/hm/status.md`、`openspec/specs/daily-workflow/spec.md`、`openspec/specs/mcp/spec.md`、`tests/test_status_entrypoint_truth.py`、OpenSpec `v2918-status-entrypoint-truth-sync` | `/hm:status` 现在默认走 `get_project_status(project_name=<project>)` 这条 triage surface；只有用户明确追问 provenance 或旧 pending 细节时，才继续下钻低层读取面。 |
| v2.9.19 | 已完成 | `docs/best-practices.md`、`tests/test_best_practices_auto_review_truth.py`、OpenSpec `v2919-best-practices-auto-review-truth-sync` | `best-practices` 现在把 `auto_review_candidates(project_name=<project>, apply=true)` 写成默认 distill review surface；`list_candidates` 只保留给显式 drilldown/recheck。 |
| v2.9.20 | 已完成 | `README.md`、`tests/test_readme_distill_truth.py`、OpenSpec `v2920-readme-distill-workflow-truth-sync` | README 的 distill workflow 图现在直接指向 `auto_review_candidates(apply=true)`；不再把 `list_candidates -> auto-review / confirm / reject` 画成 shipped 主链。 |
| v2.9.21 | 已完成 | `docs/v2-user-test-packet.md`、`tests/test_v2_user_test_packet_distill_truth.py`、OpenSpec `v2921-user-test-packet-distill-truth-sync` | v2 user test packet 的 generic MCP distill 流现在直接指向 `auto_review_candidates`；不再把 `list_candidates -> auto_review_candidates` 记成默认测试主链。 |
| v2.9.22 | 已完成 | `tools/session-distill/SKILL.md`、`plugins/harness-mem/README.md`、`tests/test_session_distill_skill_truth.py`、OpenSpec `v2922-session-distill-skill-truth-sync` | session-distill skill 与 plugin distill 摘要现在默认走 `auto_review_candidates(project_name=<project>, apply=true)`；`list_candidates` / `confirm_*` / `reject_*` 只保留给 drilldown 或 repair。 |
| v2.9.23 | 已完成 | `AGENTS.md`、`tests/test_agents_distill_truth.py`、OpenSpec `v2923-agents-distill-truth-sync` | 根 AGENTS 现在把 distill 主链直接写成 `prepare_session_distill -> suggest_* -> auto_review_candidates(project_name=<project>, apply=true)`；旧的 `list_candidates + confirm/reject` 只保留给 repair/drilldown。 |
| v2.9.24 | 已完成 | `docs/roadmap-v22x.md`、`tests/test_roadmap_v22x_distill_truth.py`、OpenSpec `v2924-roadmap-v22x-distill-truth-sync` | 历史 v2.2 roadmap 里仍会描述 active distill contract 的那一行，现在已直接指向 `auto_review_candidates(apply=true)`；不再保留 `list_candidates -> auto-review/confirm/reject` 的旧写法。 |
| v2.9.25 | 已完成 | `docs/README.md`、`docs/roadmap-status.md`、`tests/test_v29_index_truth.py`、OpenSpec `v2925-v29-index-truth-sync` | 高可见文档索引现在把 v2.9 正确描述成从 `/hm:prd-sync` 起步、随后延伸成 maintenance / truth-sync release train；不再把整个版本线缩成单一 `PRD sync candidate surface`。 |
| v2.9.26 | 已完成 | `docs/roadmap-status.md`、`tests/test_roadmap_status_summary_truth.py`、OpenSpec `v2926-roadmap-status-summary-truth-sync` | `roadmap-status` 的短结论现在也同步到当前真值：版本线已连续收口到 v2.9，而不再停留在“完成到 v2.8”的旧总结。 |
| v2.9.27 | 已完成 | `docs/roadmap-v29.md`、`tests/test_roadmap_v29_theme_truth.py`、OpenSpec `v2927-roadmap-v29-theme-truth-sync` | `roadmap-v29` 顶部主题与目标摘要现在也同步到当前真值：v2.9 不再只被定义成单一 `PRD sync candidate surface`，而是从该切片起步、随后扩成 maintenance / triage / truth-sync release train。 |
| v2.9.28 | 已完成 | `docs/roadmap-status.md`、`tests/test_roadmap_status_baseline_truth.py`、OpenSpec `v2928-roadmap-status-baseline-truth-sync` | `roadmap-status` 顶部“当前收口基线”摘要现在也同步到当前真值：不再只枚举到 `v2.9.11`，而是明确把 `v2.9.0–v2.9.27` 视作同一条已完成的 release train。 |
| v2.9.29 | 已完成 | `docs/roadmap-status.md`、`tests/test_roadmap_status_matrix_truth.py`、OpenSpec `v2929-roadmap-status-matrix-truth-sync` | `roadmap-status` 完成矩阵现在不会再把历史版本行标成“当前收口基线”；只有当前版本保留 `当前版本` 状态。 |
| v2.9.30 | 已完成 | `docs/roadmap-v25.md`、`tests/test_roadmap_v25_status_truth.py`、OpenSpec `v2930-roadmap-v25-status-truth-sync` | `roadmap-v25` 头部状态与 v2.5.2 小节现在都同步到当前真值：不再把 v2.5 写成进行中，也不再把 `file_context` 写成“待发版”。 |
| v2.9.31 | 已完成 | `docs/roadmap-v22x.md`、`tests/test_roadmap_v22x_status_truth.py`、OpenSpec `v2931-roadmap-v22x-status-truth-sync` | `roadmap-v22x` 头部状态现在也同步到当前真值：不再把 v2.2 写成“规划中”，而是明确登记为已完成版本线。 |
| v2.9.32 | 已完成 | `docs/roadmap/dream-mechanism-absorption-v151-v17.md`、`docs/README.md`、`tests/test_historical_draft_status_truth.py`、OpenSpec `v2932-historical-draft-status-truth-sync` | `docs/roadmap/` 下的历史设计稿不再只标裸 `draft`；它现在明确写成历史草稿归档，并指向 `roadmap-status` / `CHANGELOG` 作为当前真值来源。 |
| v2.9.33 | 已完成 | `docs/roadmap-vision-v16-v18.md`、`docs/reference-projects.md`、`docs/README.md`、`tests/test_vision_authority_truth.py`、OpenSpec `v2933-vision-authority-truth-sync` | `vision` 与 reference 文档现在都明确回写到当前真值：相关 `v1.6` - `v1.8` 已是历史已完成版本线，当前状态应以 `roadmap-status` / `CHANGELOG` 为准。 |
| v2.9.34 | 已完成 | `docs/roadmap-status.md`、`tests/test_roadmap_status_baseline_truth.py`、OpenSpec `v2934-roadmap-status-v29-baseline-tail-sync` | `roadmap-status` 顶部“当前收口基线”摘要现在不再把 `v2.9` release train 截在 `v2.9.27`；它已同步到当前版本尾号，并由 focused guard 跟随 `__version__` 校验。 |
| v2.9.35 | 已完成 | `docs/README.md`、`tests/test_docs_readme_status_range_truth.py`、OpenSpec `v2935-docs-readme-status-range-truth-sync` | `docs/README.md` 里的 `roadmap-status.md` 索引说明现在与当前矩阵真值一致：不再把覆盖范围缩成 `v1.6–v2.9`，而是明确包括 `v1.5.x`。 |
| v2.9.36 | 已完成 | `docs/roadmap-status.md`、`tests/test_roadmap_status_summary_truth.py`、OpenSpec `v2936-roadmap-status-short-summary-scope-sync` | `roadmap-status` 的短结论现在不再只从 `v2.2` 起讲，而是明确把 `v1.5` 到 `v2.9` 的已完成主线作为连续历史范围来总结。 |
| v2.9.37 | 已完成 | `docs/roadmap-status.md`、`tests/test_roadmap_status_version_index_truth.py`、OpenSpec `v2937-roadmap-status-version-index-truth-sync` | `roadmap-status` 的高可见版本索引现在从 `v1.5.x` 连续覆盖到 `v2.9.x`；不再以“后续 Roadmap”名义只从 `v2.2.x` 起列。 |
| v2.9.38 | 已完成 | `docs/roadmap-status.md`、`tests/test_roadmap_status_baseline_truth.py`、OpenSpec `v2938-roadmap-status-baseline-scope-sync` | `roadmap-status` 顶部 baseline 摘要现在不再只从 `v2.5` 起讲，而是明确覆盖 `v1.5` 到 `v2.9` 的连续已完成主线。 |
| v2.9.39 | 已完成 | `README.md`、`AGENTS.md`、`tests/test_opt_in_hook_truth.py`、OpenSpec `v2939-opt-in-hook-truth-sync` | README 和 AGENTS 现在都不再把“没有 IDE hook”写成绝对句，而是明确：没有默认自动随手记，但已存在默认 off 的 opt-in host hook / scheduler trigger。 |
| v2.9.40 | 已完成 | `docs/best-practices.md`、`tests/test_best_practices_wake_drilldown_truth.py`、OpenSpec `v2940-best-practices-wake-drilldown-truth-sync` | `best-practices` 现在把 `wake` 明确写成默认 read surface，并把 `get_task_handoffs` / `get_confirmed_rules` 收成显式 drilldown；不再把它们摆成默认 wake-up 起点。 |
| v2.9.41 | 已完成 | `docs/roadmap-v29.md`、`tests/test_roadmap_v29_status_tail_truth.py`、OpenSpec `v2941-roadmap-v29-status-tail-truth-sync` | `roadmap-v29` 顶部状态行此前已从 `v2.9.39` 推进到 `v2.9.40`，不再把这条 release train 的头部摘要截在更旧尾号。 |
| v2.9.42 | 已完成 | `docs/roadmap-v29.md`、`tests/test_roadmap_v29_status_tail_truth.py`、OpenSpec `v2942-roadmap-v29-status-range-truth-sync` | `roadmap-v29` 顶部状态行现在进一步收束成范围式摘要：直接写成 `v2.9.0–v<current> 已完成`，并由 test 跟随 `__version__` 校验，不再每发一版就因手工 patch 枚举而立刻过时。 |
| v2.9.43 | 已完成 | `docs/v2-user-test-packet.md`、`tests/test_v2_user_test_packet_contract_source_truth.py`、OpenSpec `v2943-user-test-packet-contract-source-truth-sync` | `v2-user-test-packet` 现在回指主 `openspec/specs/daily-workflow/spec.md` 作为契约真值源，并把 Codex MCP 接入说明写成 repo 当前维护并验证的 stdio 契约，不再依赖归档 change 路径或“当前版本客户端支持写法”。 |
| v2.9.44 | 已完成 | `docs/roadmap-v29.md`、`tests/test_roadmap_v29_archive_pointer_truth.py`、OpenSpec `v2944-roadmap-v29-archive-pointer-truth-sync` | `roadmap-v29` 里最早一批已完成切片现在统一回指 archive 真路径：`v290`–`v2912` 不再写成仍在 `openspec/changes/v29xx...` 的 active-change 路径。 |
| v2.9.45 | 已完成 | `docs/roadmap-v27.md`、`docs/roadmap-v28.md`、`tests/test_roadmap_v27_v28_archive_pointer_truth.py`、OpenSpec `v2945-roadmap-v27-v28-archive-pointer-truth-sync` | `roadmap-v27` / `roadmap-v28` 现在也统一回指 archive 真路径：`v270`–`v272` 与 `v280`–`v282` 不再写成仍在 `openspec/changes/v27x...` / `v28x...` 的 active-change 路径。 |
| v2.9.46 | 已完成 | `docs/roadmap-v16x.md`、`docs/roadmap-v17x.md`、`docs/roadmap-v23.md`、`tools/session-distill/SKILL.md`、`tests/test_historical_archive_pointer_truth.py`、OpenSpec `v2946-historical-roadmap-and-skill-archive-pointer-truth-sync` | 历史 roadmap / skill 现在也统一回指 archive 真路径与当前 `metabolism` 主 spec：不再把 `v161`、`v170`–`v173`、`v231` 写成 active-change 路径，也不再引用不存在的 `memory-metabolism` spec 目录。 |
| v2.9.47 | 已完成 | `docs/README.md`、`tests/test_docs_readme_openspec_layout_truth.py`、OpenSpec `v2947-docs-readme-openspec-layout-truth-sync` | `docs/README.md` 现在明确区分 `openspec/specs/`、`openspec/changes/` 和 `openspec/changes/archive/` 三层职责，不再把主 spec 和 change 目录混成同一种“设计规格”口径。 |
| v2.9.48 | 已完成 | `docs/v2-user-test-packet.md`、`tests/test_v2_user_test_packet_contract_source_truth.py`、OpenSpec `v2948-user-test-packet-openspec-source-hierarchy-sync` | `v2-user-test-packet` 现在明确默认先看 `openspec/specs/...` 作为主 spec 真值；只有确有 active change proposal 时，才下钻 `openspec/changes/<change>/specs/...`。 |
| v2.9.49 | 已完成 | `README.md`、`AGENTS.md`、`tests/test_repo_openspec_layout_truth.py`、OpenSpec `v2949-root-readme-and-agents-openspec-layout-truth-sync` | repo 根说明面现在也明确区分 `openspec/specs/`、`openspec/changes/` 和 `openspec/changes/archive/`；不再把 OpenSpec 写成一个笼统 `openspec/` 目录桶。 |
| v2.9.50 | 已完成 | `README.md`、`AGENTS.md`、`tests/test_root_truth_authority_sync.py`、OpenSpec `v2950-root-truth-authority-sync` | repo 根入口现在明确把当前发版状态、已完成切片和未做边界 authority 指向 `docs/roadmap-status.md` 与 `CHANGELOG.md`；各版本 roadmap 只作为设计与历史决策链，不单独充当当前实现真值。 |
| v2.9.51 | 已完成 | `docs/README.md`、`tests/test_docs_readme_truth_authority_sync.py`、OpenSpec `v2951-docs-readme-truth-authority-sync` | docs 文档索引入口现在也明确把当前发版状态、已完成切片和未做边界 authority 指向 `roadmap-status.md` 与 `CHANGELOG.md`；各版本 roadmap 只作为设计与历史决策链，不单独充当当前实现真值。 |
| v2.9.52 | 已完成 | `plugins/harness-mem/README.md`、`docs/best-practices.md`、`tests/test_usage_docs_truth_authority_sync.py`、OpenSpec `v2952-usage-docs-truth-authority-sync` | 高可见使用文档现在也明确把当前发版状态、已完成切片和未做边界 authority 指向 `roadmap-status.md` 与 `CHANGELOG.md`；它们聚焦安装、集成和使用建议，不单独充当当前实现真值。 |
| v2.9.53 | 已完成 | `docs/cli/v2.4.md`、`docs/error-codes.md`、`docs/cli-design-expert.md`、`tests/test_reference_docs_truth_authority_sync.py`、OpenSpec `v2953-reference-docs-truth-authority-sync` | 高可见参考文档现在也明确把当前发版状态、已完成切片和未做边界 authority 指向 `roadmap-status.md` 与 `CHANGELOG.md`；它们聚焦 operator reference、错误码和设计原则，不单独充当当前实现真值。 |
| v2.9.54 | 已完成 | `docs/roadmap-v22x.md`、`docs/roadmap-status.md`、`tests/test_v22_manual_gate_truth.py`、OpenSpec `v2954-v22-manual-gate-truth-sync` | 该版本当时把 `v2.2` 的完成性表述收回到彼时真值：runtime / contract 与 automated non-Claude parity 已落地，但手工 gate 仍未闭环；这个缺口后来已由 `v2-user-test-packet` 的 additional non-Claude Run log entries 补齐。 |
| v2.9.55 | 已完成 | `docs/v2-user-test-packet.md`、`docs/roadmap-v22x.md`、`docs/roadmap-status.md`、`tests/test_v22_manual_gate_truth.py`、OpenSpec `v2955-v22-non-claude-smoke-log-sync` | `v2-user-test-packet` 已有 `2026-05-25` Claude Code gate entry 与 `2026-06-03` Codex + generic MCP 两条 non-Claude entry，因此 OpenSpec archive `5.5` 手工 gate 现已满足；但 full 12-scenario cross-client matrix 仍未补齐，这部分转为后续覆盖面扩展，而不再是 v2.2 release blocker。 |
| v2.9.56 | 已完成 | `harness_mem/embedding/model_loader.py`、`harness_mem/storage/sqlite_index.py`、`tests/test_disable_embeddings.py`、`docs/v2-user-test-packet.md`、OpenSpec `v2956-fresh-home-write-path-embedding-failfast` | fresh isolated home 下，interactive write path 现在不会再因为首次 Hugging Face 模型下载而卡住：cold cache 时直接跳过 vec 写入并记 warning；现有 timeout/circuit-breaker 继续覆盖 cached-but-hung encode/import。packet 现在也已有 `2026-06-04` generic MCP fresh-home smoke，证明 embeddings enabled、empty cache 条件下的 real stdio `suggest_memory_entry` 已能快速返回。 |
| v2.9.57 | 已完成 | `docs/v2-user-test-packet.md`、`tests/test_v2_user_test_packet_empty_evidence_truth.py`、OpenSpec `v2957-generic-mcp-empty-packet-s6-evidence` | `v2-user-test-packet` 现在又补了一条 generic MCP 的正式 scenario evidence：isolated temp home 下，`prepare_session_distill(run_ingest=false)` 已在当前机器上实跑并返回 `observation_count = 0`、零 status counters 和空 `observations` 包。这把 generic MCP coverage 从最小 smoke / S8 / S9 / fresh-home write-path 再向 packet `S6 Empty evidence packet` 推进了一步，但 full 12-scenario matrix 仍未补齐。 |
| v2.9.58 | 已完成 | `docs/v2-user-test-packet.md`、`tests/test_v2_user_test_packet_cross_session_truth.py`、OpenSpec `v2958-generic-mcp-cross-session-s10-evidence` | `v2-user-test-packet` 现在又补了一条 generic MCP 的 live S10 近邻证据：两个独立 stdio MCP 会话共用同一 temp home 时，writer 会话确认的 memory entry，reader 会话随后 `wake(no_auto_ingest=true)` 已能在 `# Essential Truth (L1 · confirmed current)` 中读回。这把 generic MCP coverage 从单会话 smoke 再推进到了跨会话 truth visibility，但还不是更强的 UI 级 cross-client pair。 |
| v2.9.59 | 已完成 | `docs/v2-user-test-packet.md`、`tests/test_v2_user_test_packet_review_only_truth.py`、OpenSpec `v2959-generic-mcp-s12-repair-only-summary` | `v2-user-test-packet` 现在又补了一条 generic MCP 的 live S12 近邻证据：successful `auto_review_candidates(..., apply=true)` summary payload 已经不再含 `/hm:review`，而是直接给出 deferred candidates 的自然语言 follow-up。这把 generic MCP coverage 从“能成功 auto-review”进一步推进到了“summary 仍保持 repair-only boundary”。 |
| v2.9.60 | 当前版本 | `docs/v2-user-test-packet.md`、`tests/test_v2_user_test_packet_stale_cli_truth.py`、OpenSpec `v2960-packet-s11-stale-cli-surface-evidence` | `v2-user-test-packet` 现在又补了一条 S11 repo-truth evidence：packet 规定扫描范围内，`harness-mem wake/search/timeline/candidates/distill` 已不再作为当前用户 path 教学出现，grep 命中只剩“这些 CLI 面已经删除/不要求手动跑”的反例说明。这把 packet 从“定义了扫描命令”推进到了“记录了当前扫描结果”。 |

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

## 规划中

这些条目是未来版本设计，不要冒充已发布：

| 切片 | 状态 | 目标 | 文档 |
|---|---|---|---|
| v3.1.x Auto Dream Memory Maintenance | 规划中，未实现 | 用户显式开启后自动做梦、自动解析所有梦境结果、自动处理全部结果；不产生待确认队列；用户只通过 `/hm:dream` 查看梦境账本或撤销处理。 | `docs/roadmap-v31.md` |

## 版本索引

| 切片 | 主题 | 文档 |
|---|---|---|
| v1.5.x | Retrieval baseline + ingest/onboarding 基础：自动 ingest、跨项目搜索、doctor/安装闭环 | `docs/roadmap-v15x.md` |
| v1.6.x | Persistent vectors + memory typing + bucket budget：measurement foundation、typing、persistent vectors | `docs/roadmap-v16x.md` |
| v1.7.x | Temporal truth + supersede + bounded relation graph：temporal schema、supersede、verbatim exact evidence search | `docs/roadmap-v17x.md` |
| v1.8.x | Procedural memory 保守闭环：`ProceduralCandidate`、confirmed `Skill`、`search_skills`、`record_skill_result` | `docs/roadmap-vision-v16-v18.md` |
| v2.0.x | Heuristic distill 移除：distill 从 heuristic runtime 收束成 LLM agent 流程 | `docs/roadmap-status.md` |
| v2.1.x | Maintenance-only CLI + Slash/Skill/Agent workflow 重写：daily-memory surface 退出 CLI | `docs/roadmap-status.md` |
| v2.2.x | AI IDE 入口闭环：`/hm:distill`、`/hm:wake`、`/hm:search`、跨客户端测试、auto-review UX | `docs/roadmap-v22x.md` |
| v2.3.x | Signals / Replay 地基：`RetrievalSignal`、`MetabolismRun`、replay window、`metabolism_preview` | `docs/roadmap-v23.md` |
| v2.4.x | Host-triggered Reflection + Queue Health：job lifecycle、config toml、维护子命令管配置、hook 仅业务命令、doctor | `docs/roadmap-v24.md` |
| v2.5.x | Context Assembly + File Context：Memory Stack renderer、file-context、分层 wake | `docs/roadmap-v25.md` |
| v2.6.x | Wiki Bridge + Compact Index + Contradiction：knowledge cache、claim index、stale/merge/supersede suggestions | `docs/roadmap-v26.md` |
| v2.7.x | Cross-Project Skills + Controlled Activation：shared skills、skill hints、skill improvement suggestions | `docs/roadmap-v27.md` |
| v2.8.x | Session-Distill Maintenance Surfaces：`/hm:mark`、`/hm:prune`、`/hm:review-kb`、`/hm:prune-kb`、`/hm:verify-entry` 的正式版本线 | `docs/roadmap-v28.md` |
| v2.9.x | PRD sync 起步，随后扩成 maintenance / triage / truth-sync release train：`/hm:prd-sync`、`/hm:status`、plugin doctor helper、maintenance CLI collateral、reflection/config truth sync、wake/distill/status 入口真值收口 | `docs/roadmap-v29.md` |
| v3.1.x | Auto Dream Memory Maintenance：自动做梦、自动解析、自动处理全部结果，单入口 `/hm:dream` 梦境账本 | `docs/roadmap-v31.md` |

## 短结论

从 v1.5 baseline 到 v2.9 release train，主实现路线已经按一个版本一个文档重切并连续收口。
v1.5 baseline、v1.6 persistent vectors / bucket budget、v1.7 temporal truth、
v1.8 procedural skill、v2.0 heuristic distill 移除、v2.1 maintenance-only CLI、
v2.2 用户入口闭环（runtime / contract 已落地，且 OpenSpec `5.5` 手工 gate 已由 Claude Code + non-Claude Run log 满足；Cursor hook install 与真实 agent run-log 证据也已出现，但 full matrix coverage 仍可继续扩展）、
v2.3 signals/replay、v2.4 reflection queue、v2.5 context assembly、v2.6
wiki/contradiction、v2.7 cross-project skill、v2.8 session-distill maintenance，
以及 v2.9 的 PRD sync / maintenance / triage / truth-sync release train 都已落地。

v2.4 reflection queue 四个切片（v2.4.0–v2.4.3）已实现、验证并发版。
v2.5 context assembly 与 file context、v2.6 knowledge cache / wiki /
candidate-only contradiction boundary、v2.7 shared skill / controlled
activation / reviewed improvement suggestions、v2.8 session-distill
maintenance surfaces，以及 v2.9 的 `/hm:prd-sync`、`/hm:status`、maintenance
CLI collateral truth、reflection/config truth sync、wake/distill/status
entrypoint truth sync 都已并入正式版本线。当前仍未启用 always-on daemon，
MCP stdout 纯净性继续保持，shared skill 也仍然坚持显式消费。

优先级依据是：没有 signals 就无法 replay；没有 queue health 就无法安全 reflection；
没有 context assembly，更多 memory / skill 只会变成可搜索对象而不是真正可控的 agent memory。

下一条规划线是 v3.1 Auto Dream Memory Maintenance：在默认关闭、用户显式开启的前提下，把 signals / metabolism / reflection queue 组合成自动维护循环。v3.1 的设计目标是自动解析并处理全部梦境结果，不产生待确认队列；但每个处理都必须保留 DreamRun 审计、evidence、policy reason 和 undo path，且不 hard delete confirmed truth。

