# Changelog

所有正式版本变更记录。格式参照 [Keep a Changelog](https://keepachangelog.com/)。

---

## [Unreleased]

---

## [2.4.3] — 2026-05-30

**主题：Host-triggered Reflection 全线落地 + 维护 CLI — v2.4.0 到 v2.4.3**

v2.4 把 reflection / distill 这类较重任务收敛成一套**安全的 host-triggered 闭环**：由 user / Agent / IDE hook / scheduler 在配置允许时触发，默认 `triggers.* = off` 时零副作用；人通过维护子命令管配置、装 hook；hook 只调 `python -m harness_mem.host_entry`，从不调 `harness-mem` 控制台脚本。整条线遵守 candidate-before-truth，不引入 always-on daemon。本版本号一次性收口 v2.4.0–v2.4.3 四个切片。

### Added

- **v2.4.0 Reflection Job Model**：`ReflectionJob` schema 与状态机（`pending / processing / completed / failed / retryable / needs_distill`）、processing lease（超时转 retryable）、provenance（`user | agent | ide_hook | scheduler` + project + phase + candidate ids）、retry policy（不重复写相同 candidate）、job list/read MCP helper。
- **v2.4.1 Host-Triggered Reflection Contract**：`harness_mem/config/`（`errors` + `load_merged_config` + 冻结 `MergedConfig`，用户级/项目级 TOML deep-merge）、`harness_mem/host_entry/`（`python -m` 入口、argparse、`HostEntryResult` 输出契约、`ExitCode`）。MCP 与 host 入口共用同一业务实现，对同一 fixture 产出一致 job/ingest 结果。
- **v2.4.2 Queue Health & Doctor**：doctor 的 queue / stale candidate / signal freshness / chronic failures 检查、maintenance hints、结构化 health summary（供 MCP 消费）。只读，不自动修复。
- **v2.4.3 CLI Configuration & Integration**：`harness-mem config get/set/list/validate`（读经 `load_merged_config`，写经新增 `harness_mem/config/writer.py`，`tomli_w`）；`harness-mem integration install-cursor-hook` / `install-claude-hook`（`harness_mem/integration/` 模板 + installer + 边界自检）。`docs/cli/v2.4.md` 操作者参考。
- **Embeddings opt-out 开关**：`HARNESS_MEM_DISABLE_EMBEDDINGS` 在 `persist_embedding` 与 hybrid search 路径跳过 SentenceTransformer/torch 加载，便于无模型 / CI 环境运行测试；env 未设时生产默认行为不变。
- **Distillation 维护入口**：`/hm:mark`、`/hm:prune`、`/hm:review-kb`、`/hm:prune-kb`、`/hm:verify-entry` 成为一等 Slash 管理动作；session-distill guardrails 与 knowledge-base 审计工具；轻量 distillation 提醒。

### Changed

- `harness-mem` CLI 顶层新增 `config` 与 `integration` 两个维护子命令；CLI 维持 maintenance-only，不暴露 `reflection / distill / ingest / wake` 业务子命令（scope guard 测试守卫）。
- `pyproject.toml` 新增 `tomli_w>=1.0,<1.3` 运行时依赖（TOML 写入）。
- `docs/roadmap-status.md` 补登 v2.4.0–v2.4.3 完成矩阵与边界。

### Boundary / Non-Goals

- 默认 `triggers.after_agent = off` / `triggers.scheduler = off`：装了 hook 也不会自动 reflection，需显式 `config set triggers.after_agent on --scope project` 才 opt-in。
- 无 always-on daemon（`worker.mode=daemon` 须 opt-in 且无 CLI 安装器）。
- 生成的 hook 只嵌入 `python -m harness_mem.host_entry --source ide_hook`，hook 失败 `exit 0` 不阻断 IDE 回合；host 触发不静默写 confirmed truth。

### Test surface

- v2.4.3 维护 CLI 面 127 passed；v2.4.1 config/host_entry 面 123 passed；v2.4.0–v2.4.2 回归 320 passed。
- 全量非 benchmark 套件（`HARNESS_MEM_DISABLE_EMBEDDINGS=1`）881 passed / 7 skipped（7 项需真实 embedding 模型，已用 skip marker 守卫）。
- ruff clean；mypy clean（host_entry / config / cli）。

---

## [2.3.1] — 2026-05-27

**主题：Metabolism Suggestion Pass — 从 replay window 生成可审核的代谢建议**

v2.3.1 把 v2.3.0 的 signals / replay 地基升级为显式 suggestion pass。它仍然遵守 candidate-before-truth：系统可以提出 merge / stale 建议，但不能静默改 confirmed truth。

### Added

- **`MergeSuggestionCandidate` 与 `StaleTruthSuggestionCandidate`**：新增两类可审核代谢候选及对应 SQLite index / JSON blob 存储、读路径和测试。
- **`metabolism_run` MCP tool**：写侧工具会运行 suggestion pass，持久化 `MetabolismRun(kind="metabolism")`，并保存 merge / stale / supersede 计数。`metabolism_preview` 保持只读。
- **`select_metabolism_pass(...)`**：基于 replay window 生成 merge / stale / supersede 三路输出。v2.3.1 中 merge 只处理 `memory_entry`-`memory_entry`，stale 处理 current `memory_entry` / `confirmed_rule`，supersede proposer 明确 deferred。
- **Content-based token trim**：`count_tokens()` 优先使用 `tiktoken` `cl100k_base`，不可用时降级到 char heuristic，再降级到 dimension weight，并把 fallback 写入 window notes。
- **Weak-link signal influence**：`ProjectProfile.weak_link_signals` 默认关闭；开启后 wake 将 confirmed rules 分为 `Recent active` / `Stable / quiet`，search 对近 7 天重复命中 entry 增加小幅 boost。
- **Doctor signal visibility**：`doctor` 输出 weak-link signal influence 状态和 enabled/disabled 诊断。
- **Calibration notes**：`tests/metabolism/calibration.md` 记录 similarity、silence、repeat-boost 阈值 fixture 结果。

### Changed

- `read_api.search_memory` 在 `weak_link_signals=True` 时会基于近期 repeated `search_hit` signal 调整 memory entry 排序；关闭时保持 v2.2/v2.3.0 行为。
- `wake` renderer 在 `weak_link_signals=True` 时对 confirmed rules 做 opt-in 分组；关闭时输出与旧行为保持一致。
- `MetabolismRun.from_dict` 兼容旧 `{"suggestions": 0}` output_counts，也支持新三类 suggestion counters。
- `AGENTS.md`、`README.md`、`tools/session-distill/SKILL.md` 和 roadmap 文档补充 metabolism_run、candidate types、weak-link opt-in 边界。

### OpenSpec

- 归档 `v231-metabolism-suggestion-pass`，更新 `openspec/specs/metabolism/spec.md`。

### Test surface

- 414 passed, 1 skipped。
- mypy 0 errors / 82 source files。ruff clean。`openspec validate --all --strict` 全绿（22 items）。

---

## [2.3.0] — 2026-05-26

**主题：Memory Metabolism Foundation — signals、replay window 与 preview-only run**

v2.3.0 给 memory metabolism 铺地基：记录记忆如何被 wake/search/review/skill/supersede 消费，并提供只读 preview window。它不生成 suggestion、不改 truth、不改变默认 wake/search/distill 输出。

### Added

- **`RetrievalSignal` schema 与存储**：记录 `confirmed`、`rejected`、`wake_surfaced`、`search_hit`、`skill_result_success`、`skill_result_failure`、`supersede_completed` 等信号。
- **`MetabolismRun` schema 与存储**：记录 preview/metabolism run 的 project、input window、selected signals、output counts、duration、status 和 notes。
- **`record_retrieval_signal(...)` shadow write helper**：signal 写入失败只记录日志，不影响主调用。
- **Replay window selector**：从 recent observations、stale pending candidates、historical truth、low-success skills、repeat search hits 中按预算选取 preview window。
- **`metabolism_preview` MCP tool**：显式返回 replay window 摘要和入选理由，并写 `MetabolismRun(kind="preview", status="preview")`。

### Changed

- wake/search/auto-review/skill-result/supersede 路径增加 signal shadow write；用户可见输出不变。
- `tools/session-distill/SKILL.md`、`AGENTS.md` 和 roadmap 文档明确 v2.3.0 只有 preview，没有用户可见新入口。

### OpenSpec

- 归档 `v230-signals-and-replay-windows`，新增 `openspec/specs/metabolism/spec.md`。

### Test surface

- pytest / ruff / mypy / OpenSpec release gate 在 v2.3.0 收口时通过。

---

## [2.2.0] — 2026-05-25

**主题：AI IDE 入口闭环 — 锁住 Slash / Skill / 自然语言 golden path，让 auto-review 真正"自动"**

v2.2 不加新能力，把 v2.0 / v2.1 累积下来的"用户走 IDE 入口、Agent 背后调 MCP、CLI 只做维护"承诺正式拼成可测试的契约。前一个版本砍掉了误导 surface（heuristic distill、daily CLI、REST API），但承诺与实现的对齐还散在各文件里；v2.2 把它收成一份 spec、一份跨客户端测试矩阵、一组防回归扫描，以及更稳健的 auto-review UX。

### Added

- **MCP error visibility**：`handle_request` 抛异常时返回的 `error.message` 现在带异常 class + message（例如 `"Internal tool error in suggest_memory_entry: RuntimeError: ..."`）。Traceback 仍只进 stderr 不泄露文件路径。配套 regression test `tests/mcp/test_smoke.py::test_tool_error_message_includes_class_and_message`。背景：v2.2 release gate 测试时 tester 收到通用 "Internal tool error" 无法定位根因，后来发现是 stale MCP server 进程，但 fix 让未来同类问题第一时间可诊断。
- **`openspec/specs/daily-workflow/` spec**：固化 8 条 user-visible workflow 契约——entrypoint、project resolution、distill 闭环、5 类 failure 文案、auto-review 共享策略、evidence-id 强约束、kept-pending vs needs-user-confirmation 拆分、6 项 canonical counters、`/hm:review` 作为 repair-only 入口。
- **跨客户端测试矩阵 `docs/v2-user-test-packet.md`**：从 v2.0 三 persona 脚本升级为 4 客户端 × 12 scenario 矩阵，覆盖 Claude Code / Codex CLI / Cursor / generic MCP client。每个 scenario 给 Intent / Pre-condition / Per-client input / Expected / Pass criterion / Common failure mode 六个维度；客户端特异失败必须落到 docs / prompt PR，禁止 IM tribal knowledge。
- **stale-doc 防回归扫描 `tests/test_stale_cli_surface.py`**：参数化扫描 README / AGENTS / plugin docs / SKILL.md，断言 `harness-mem wake/search/timeline/candidates/distill` 这五个 v2.0 砍掉的 daily 子命令不会以"用户教学"形式重现。允许列表只覆盖明确的负面引用（如 AGENTS.md 描述 v2.0 移除的那行）。
- **agent-without-CLI 回归测试 `tests/loop_harness/test_agent_distill_closed_loop_no_cli.py`**：覆盖 `set_active_project → suggest_memory_entry → list_candidates → auto_review_candidates` 全链通过 MCP 的 happy path，断言六计数器 summary 字段齐全、`applied_decisions` 含 `candidate_id + reason`。
- **`AutoReviewDecision.evidence_id` 与 `is_high_risk` 字段**：每条决策直接携带证据来源 id（`MemoryEntry.source` 或 `RuleCandidate.examples[0]`），让"为什么 X 被自动 confirm/reject?"问题有可解释答案；`is_high_risk` 把 defer 拆成静默挂起 vs 需要用户确认。
- **`explain_decision(summary, candidate_id)` helper**：`/hm:distill` / Skill 流程在用户追问"why"时一行调用即可拿到 `{candidate_id, kind, action, reason, evidence_id}`。
- **5 类噪声 fixture**：tool failure、cross-project workflow leakage、generic advice、distill-process self-reference、duplicate candidate。`tests/test_auto_review_noise_fixtures.py` 提供 24 个用例，其中 duplicate 走 `auto_review_candidates(apply=True)` 验证 reason 引用首条 id。

### Changed

- **`harness_mem/commands/auto_review.py` 成为唯一 auto-review 真值源**：`/hm:distill` slash、`session-distill` skill、MCP `auto_review_candidates` 三个调用方共用同一份策略（noise patterns / 阈值 / 类别白名单 / 证据校验）。模块顶部新增 "Shared policy contract" 段记录这条契约。
- **Auto-confirm 规则收紧**：`MemoryEntry` 自动确认要求 `source != "manual"` 且非空；`RuleCandidate` 自动确认要求 `examples` 非空。证据缺失则 defer 并标 `is_high_risk=True`，让用户看见。
- **同 pass 内重复候选自动 reject**：按 `(project, category, content[:200].lower())` 去重，第二条同内容候选 → `auto_reject` + reason `duplicate of <first_id>`。
- **Auto-review summary 拆分**：`kept_pending` 与 `needs_user_confirmation` 分开计数。低风险 defer（如 `bug` 类别需要人工 triage）只增 `kept_pending`；高风险 defer（rule candidate、`decision/architecture` 类别证据缺失）同时增 `needs_user_confirmation`。`next_user_action` 文案分三档。
- **`docs/v2-user-test-packet.md` 全面重写**：v2.0 的三 persona 脚本仍可作为 scenario 内的 flavor，但脊椎换成"同一行为跨客户端并排跑"。Run log 章节使用同文件追加而非 sibling 目录，降低运维摩擦。

### Removed

- 无 breaking 移除。v2.2 是契约固化与 UX 收尾，不动 schema / MCP 工具签名 / data 格式。

### OpenSpec

- 归档 `v220-ai-ide-entry-loop` 为 `archive/2026-05-25-v220-ai-ide-entry-loop/`。
- 新增 `openspec/specs/daily-workflow/spec.md`（8 个 Requirements / 22 个 Scenario）。

### Test surface

- 359 passed, 1 skipped（v2.1 baseline 322 → 359：新增 37 个测试覆盖 auto-review 噪声分类、stale-doc 扫描、loop harness no-CLI happy path、MCP error visibility regression、daily-workflow scenarios）。
- mypy 0 errors / 73 source files。ruff clean。`openspec validate --all --strict` 全绿（20 specs）。

### Manual release gate

- v2.2 client test packet 必须由测试者跑 Claude Code + 至少一个非 Claude client（Codex / Cursor / generic MCP），结果记录到 `docs/v2-user-test-packet.md` 的 Run log 章节。本版本的 Run log 入口见下：

  ```
  ## YYYY-MM-DD — <tester>
  Clients: <list>
  Pass: <scenarios>
  Fail: <scenarios + 描述>
  Fixes filed: <PR / 文档路径>
  ```

### Why this is 2.2 not 2.1.1

v2.2 是契约层的硬升级——之前承诺散在 README / AGENTS / SKILL.md 里、用户测试只有 dogfood 流；现在 daily-workflow spec 是单点契约，跨客户端 12 scenario 是可重复测试，5 类噪声 fixture 让 auto-review 行为可解释。这超出了 patch 范围。但 schema / MCP 签名 / data 不动，所以也不是 3.0。

---

## [2.1.0] — 2026-05-24

**主题：Surface 瘦身 + 文档诚实化 — CLI 退回维护控制台，纠正"AI 随手记"承诺**

v2.1 不加新能力，做两件事：把用户路径从 CLI 子命令搬到 IDE 命令 / Skill / Agent 自然语言，把 README/AGENTS.md 里悬空的"AI 随手记"叙事改成与实现一致的描述。这是产品定位的硬转向——v2.1 之前 harness-mem 表面像个 CLI-driven memory tool，v2.1 之后表面是 invisible memory runtime，CLI 只做安装、自检、清理。

### Removed (BREAKING)

- **CLI 子命令大幅精简**。日常 memory 操作（`use`、`ingest`、`wake`、`search`、`timeline`、`status`、`profile`、`candidates`、`confirm`、`reject`、`correct`、`handoff`、`rules`、`search-raw`、`search-skills`、`suggest-skill`、`confirm-skill`、`reject-skill`、`record-skill-result`）不再注册为 `harness-mem` 子命令。CLI 现在只剩 `init` / `quickstart` (`qs`) / `doctor` / `import` / `purge` / `maintenance` 七个安装、自检、维护命令。
- **REST API 层完全移除**。删除 `harness_mem/api/__init__.py`、`harness_mem/api/models.py`、`harness_mem/api/server.py` 与对应测试。MCP 是产品的传输层；REST 不在主路径上，没有用户依赖，留着只会让接口面板膨胀。
- 与 REST API 相关的 `harness-mem api` CLI 入口同步移除。

### Changed

- **CHANGELOG / README / AGENTS.md 措辞纠正**。之前的"4 角色"叙事里"AI（操作者 / 随手）"角色描述为"日常写代码顺手记"，但产品里**没有后台 daemon、IDE hook 或 turn-end 自检**来驱动这个行为。`suggest_*` 工具确实存在并被调用，但调用 100% 来自显式 distill 流程或用户明确要求。文档现在如实写：候选写入只在显式流程里发生，autonomous learning 不属于当前实现。
- **CLI 自我描述**：`harness-mem --help` 顶部现在写 "Local harness-mem maintenance console. Daily AI memory workflows use IDE commands, repo skills, or agent workflows instead of CLI subcommands."
- **README 重写为用户视角**：用户入口收敛到 `/hm:distill` / `/hm:wake` / `/hm:search` / 自然语言；MCP 是 Agent 背后的传输层，不是用户心智模型；CLI 是维护控制台。
- **AGENTS.md 角色表更新**：从 4 角色改为 3 角色 + 一项"候选写入能力"。明确写出当前没有 turn-end 自检 hook，`suggest_*` 是显式流程的接口而非自治学习的痕迹。
- **Roadmap 状态页**：新增 `docs/roadmap-status.md`，明确 v1.8 已完成的是保守 procedural-skill 闭环，不包含后台自学习、默认 wake 注入或跨项目 skill 共享。
- **OpenSpec spec 同步**：`openspec/specs/cli/spec.md`、`ingest/spec.md`、`retrieval/spec.md`、`purge/spec.md`、`mcp/spec.md`、`telemetry/spec.md`、`memory-typing/spec.md` 里所有以已移除 CLI 命令为入口的 Scenario 重写为 IDE 命令 / Skill / 自然语言视角；CLI 命令只在 `init` / `doctor` / `purge` / `maintenance` 这类剩余子命令的 Scenario 里出现。

### Migration

- 任何脚本调用被移除的 CLI 子命令（`harness-mem wake / search / candidates / confirm / reject` 等）会立即失败。迁移到 MCP 客户端配置 + IDE 命令 / Skill。
- 读 OpenSpec spec 的人现在看到的 Scenario 是 IDE 视角（`/hm:search`、自然语言 prompt），不是 CLI。
- REST API 用户没有迁移路径——这是有意的，因为没有维护 REST 的用户基。

### Why this isn't 3.0

按 SemVer 严格定义，删 CLI 子命令和删 REST API 都是 breaking。但实际上 CLI 历来定位是"bootstrap / 试用 / dogfood"，没有外部脚本依赖；REST API 在产品 surface 上从未被推荐过。**真正的兼容性约束是 MCP 工具签名和数据 schema**——这两者在 v2.1 完全不动。

v2.1 是"产品定位转向"的标志，不是"重大功能升级"。3.0 留给真正的能力级 breaking（例如 schema 重构、跨项目记忆、或后台 daemon）。

### Test surface

- 326 → 322 passed (1 skipped)。-4 测试来自删除的 CLI 子命令路径和 REST API 测试；新增 4 个测试在 v2.0 系列已落地（`set_active_project` / `update_project_profile` / `wake` / HM-501 cwd mismatch）。
- mypy 0 errors / 73 source files。ruff clean。

---

## [2.0.0] — 2026-05-22

**主题：Heuristic distill 移除 — distill 路径只接受 LLM agent**

v2.0 是单一焦点的 breaking 切片：移除 `harness-mem distill` CLI 子命令、`tool_distill_sessions` MCP 工具、以及 `harness_mem/adapters/parser.py::HEURISTIC_PATTERNS` / `extract_heuristic_entries` / `extract_relation_facts` 整套正则启发式实现。`ClaudeCodeAdapter.distill_session` / `distill_relation_facts` 一并删除。

**为什么 breaking**：

- 启发式 distill 默认产出 confidence=0.7 的候选，恰好低于 v1.6.1 引入的 auto-review 自动确认阈值 (0.75)。loop_harness scenario 2 实测：**5/5 候选全部 defer，没有一条能进入 auto-confirm 路径**。
- 启发式 RelationFact 提取要求实体两侧大写、动词在固定六个之内、整段在同句。loop_harness scenario 6 实测：**自然 Claude/Codex prose 5 条 memory entries → 0 条 relation facts，ratio = 0.0**。
- 启发式产物长得像"AI 提炼"，但实际是低 confidence 正则匹配，违反 README 顶部的"AI memory runtime"承诺。

**用户日常路径不变**：`/hm:distill` slash + MCP `suggest_*` 工具仍是 distill 入口。任意 LLM agent (Claude Code、Codex、Cursor、Gemini、自定义) 都可以通过 MCP 写候选。

**dogfood 流不变**：可由任意 AI 工具驱动，不绑 Claude Code。

### Removed (BREAKING)

- `harness-mem distill` / `harness-mem ds` CLI 子命令。
- `tool_distill_sessions` MCP 工具（tool count 34 → 33）。
- `harness_mem/commands/distill.py` 整文件。
- `harness_mem/adapters/parser.py`: `HEURISTIC_PATTERNS`, `RELATION_FACT_PATTERNS`, `extract_heuristic_entries`, `extract_relation_facts`, `_sentence_window`。
- `harness_mem/adapters/claude_code/adapter.py`: `distill_session`, `distill_relation_facts`, `_extract_entries`, `_entry_key`, `_relation_fact_key`。
- `tests/cli/test_distill.py`, `tests/loop_harness/test_distill_precision_recall.py`, `tests/loop_harness/test_relation_graph_data_pipeline.py`。

### Kept

- `prepare_session_distill` MCP 工具（产 evidence packet 给 LLM agent，是 LLM-driven distill 路径的关键入口）。
- `tools/session-distill/SKILL.md`（Claude Code skill 实现，仍然是参考实现；其它 client 可以照样写自己的 prompt + MCP 调用）。
- `harness_mem/distill_context.py`（`DistillContext` 只读边界仍然给 MCP `suggest_*` 工具用）。
- ingest 路径完整保留（adapter session 解析、`turns_to_observation`、`harness-mem ingest` CLI、MCP `ingest_sessions`）。
- supersede / correction 路径完整保留（v1.8 引入的 `suggest_correction` 不变）。

### Migration

升级到 v2.0 不需要数据迁移。已存在的 `MemoryEntry` / `RelationFact` / `RuleCandidate` blob 完全兼容。唯一影响：

- 任何脚本 / Slash / 文档里写了 `harness-mem distill` 的，要改成"通过 LLM agent + MCP `suggest_memory_entry` 写候选"，或走 `/hm:distill` slash（Claude Code）/ 等价 skill（其它 client）。
- 任何脚本调用 MCP `distill_sessions` 工具的，要改成 `prepare_session_distill` + agent 处理 evidence packet + `suggest_memory_entry`。

### Test surface

- 352 → 325 passed (1 skipped). 删除 27 个测试用例（heuristic-only 测试），新增 / 重写 4 个（auto-review calibration 直接 seed、CLI mainline 用 LLM 路径模拟）。
- mypy 0 errors / 75 source files。ruff clean。

---

## [1.8.0] — 2026-05-22

**主题：Procedural Skill loop + v1.7 evidence closeout**

v1.8.0 把 v1.7 的时间感、supersede 审核链和证据定位收口到一个可发布版本，并新增保守版 procedural memory：AI 可以把可复用流程沉淀为候选 Skill，经显式确认后检索和记录执行结果。它仍然是可审计 memory runtime，不是后台自学习 agent。

### Added

- **Procedural memory 保守闭环**：新增 `ProceduralCandidate` 候选层与 confirmed `Skill` 层，支持 `activation_condition`、ordered `steps`、`termination_condition`、provenance、confidence 和 review status。
- **Skill review / retrieval / outcome 工具**：CLI 新增 `suggest-skill`、`confirm-skill`、`reject-skill`、`search-skills`、`record-skill-result`；MCP 新增 `suggest_skill`、`confirm_skill`、`reject_skill`、`search_skills`、`record_skill_result`。
- **Skill 成功率回写**：confirmed Skill 记录 `usage_count`、`success_count`、`failure_count`、`success_rate` 与 `last_used_at`。
- **Procedural fixtures**：新增 focused test loop、review-and-merge loop、maintenance loop 三组 fixture，验证候选形态和只读边界。
- **v1.7.3 exact evidence search**：新增 raw observation exact / regex 证据定位路径，包含 verbatim n-gram index、`search-raw`、MCP `search_raw`、`maintenance rebuild-verbatim-index` 与 doctor health hint。
- **Loop harness 骨架**：新增 `tests/loop_harness/`，覆盖 distill extraction、wake surfacing、supersede replacement 三条真跑场景，并用 `xfail` 标出 auto-review 仍缺少程序化入口。

### Changed

- `list_candidates` / MCP candidate payload 覆盖 procedural candidates，让 Skill 候选进入同一审核视图。
- MCP initialize handshake 的 `serverInfo.version` 改为读取 `harness_mem.__version__`，避免 server 元信息落后于包版本。
- `docs/roadmap-v17x.md`、`docs/roadmap-vision-v16-v18.md` 与 OpenSpec change 记录 v1.7.3 / v1.8.0 的真实完成状态。
- `README.md` 收敛为用户视角 golden path：安装 -> `/hm:distill` -> `/hm:wake` -> `/hm:search` -> `search_skills`。

### Safety Boundaries

- Procedural candidates 不会自动确认。
- Confirmed Skill 不会写入 semantic truth，不会进入默认 `wake` selection。
- v1.8.0 不做跨项目 Skill 共享、不做后台 daemon、不做自治删除或自学习强化。

### Validation

- `python -m ruff check .`
- `python -m mypy harness_mem`
- `python -m pytest -q`
- `openspec validate v173-verbatim-exact-evidence-search`
- `openspec validate v180-procedural-skill-spike`

---

## [1.7.x] — 2026-05-21

**主题：Temporal truth + supersede review + bounded graph retrieval**

v1.7.x 让 `harness-mem` 从“记住事实”前进到“知道事实什么时候有效、什么时候被替代、证据在哪里”。这组切片为 v1.8 procedural skills 打底：Skill 可以复用流程，但 semantic truth 仍然保留时间、历史和审核链。

### Added

- **Temporal structured memory**：truth-like records 支持 current/history reads，默认消费 current truth，历史事实需要显式查询。
- **Supersede candidate loop**：新增 supersede 候选审核链；确认后旧 truth 标记为 historical，不物理删除。
- **Bounded relation graph retrieval**：支持受限关系追踪和时间感检索，避免 stale truth 混入默认 wake。
- **Verbatim exact evidence search**：新增 observation raw-content exact / regex 证据定位，不替代 FTS5 / vector semantic search。

### Safety Boundaries

- v1.7 采用 mark-not-delete：旧事实保留 provenance 和历史窗口。
- Supersede 需要显式确认，不允许 distill 直接改写 confirmed truth。
- Graph traversal 有深度和预算边界，不把 SQLite runtime 扩成完整 KG 平台。

### Validation

- v1.7.x 各切片均有 storage / CLI / MCP focused tests。
- `openspec validate v170-temporal-schema-current-history`
- `openspec validate v171-supersede-candidate-loop`
- `openspec validate v172-temporal-graph-retrieval`
- `openspec validate v173-verbatim-exact-evidence-search`

---

## [1.6.2] — 2026-05-20

**主题：sqlite-vec 持久化向量 + embedding shootout 收口**

v1.6.x 的第三刀，把热路径 embedding 从查询侧移到写入侧，补齐 persistent vector storage、doctor/maintenance 健康检查、embedding model shootout 入口，并把 LongMemEval 的 v1.6.2 集成验证挂到 benchmark 标记下。

### Added

- `vec_embeddings` 持久化表与写路径落盘。
- `harness-mem maintenance rebuild-vector-index --project <name>`。
- `HM-201 / HM-202 / HM-203` 错误码与 doctor 检测。
- `harness_mem.tools.embedding_shootout` 与数据集自动定位。
- `tests/benchmark/test_longmemeval_persistent_vectors_integration.py`，作为 v1.6.2 的 LongMemEval 集成门。

### Changed

- `HybridSearchLayer` 改为优先读持久化向量；缺表、空表、全过滤时回退 FTS。
- `LocalStructuredStore.save_memory_entry()` 与 `LocalVerbatimStore.save()` 继续在写入后持久化 embedding。
- persistent vector 测试统一改为显式 `MemoryEntry(...)` 传参。

### Notes

- 默认 embedding 模型仍保留 `all-MiniLM-L6-v2`，是否切换交由 shootout 决策。
- `docs/benchmark/v162-embedding-shootout.md` 的规则 3 已拍板：`bge-small-en-v1.5` 与 `nomic-embed-text-v1.5` 未满足升级规则，默认模型保持 `all-MiniLM-L6-v2`。
- v1.6.2 的 P95 latency 目标与完整 LongMemEval 结果仍是手动 release gate；本发布只声称 runtime read path、fallback、doctor/maintenance 与 benchmark 入口已落地，CI 保留可运行门与集成 smoke。

---

## [1.6.1] — 2026-05-19

**主题：Wake-up bucket budget + distill 只读边界**

v1.6.x 三切片路线的第二刀。在 v1.6.0 把 `MemoryEntry.memory_type` 做成一等字段之后，本切片把"读分桶 + 写边界"一次落地：wake-up 输出按 `memory_type` 分桶并显式可关，distill 写动作收紧到候选层（默认 `pending`），search 三端补齐 `memory_type` 过滤。**安全边界先于能力增强**——v1.6.2 引入 sqlite-vec 持久化向量后 distill 能"读全库 + 跑聚类"，写边界不锁死会被诱惑去顺手清理 truth。

完整设计与决策见 [`docs/roadmap-v16x.md`](docs/roadmap-v16x.md)（v1.6.1 段）与 [`openspec/changes/2026-05-19-v161-bucket-budget-and-distill-readonly/`](openspec/changes/2026-05-19-v161-bucket-budget-and-distill-readonly/)。

### Added

- **wake-up 三桶预算**：`[wake]` 配置新增 `bucket_quota_semantic / bucket_quota_episodic / bucket_quota_procedural`（默认 `0.5 / 0.5 / 0.0`，见 `roadmap-v16x.md` "已决策 2"）+ `bucket_quota_enabled` 总开关。`select_wake_memory_entries_with_buckets` 按 `memory_type` 分桶选取，超额在桶内截断，未消费名额按 `semantic > episodic > procedural` 让渡（quota=0 桶不参与让渡）。
- **wake-up 输出可观测性**：wake header 在 `(...chars)` 行下追加 `bucket quotas` 与 `bucket fill` 两行；某桶内候选超额时附 `[truncated within bucket: <type> X/Y]`。
- **wake-up 显式可关**：CLI flag `harness-mem wake --no-bucket-quota` 与 config `[wake] bucket_quota_enabled = false` 同义；关闭时回到 v1.6.0 单池行为，header 不输出桶信息。
- **DistillContext + DistillReadOnlyError**：新模块 `harness_mem.distill_context`。`cmd_distill` 入口现在构造 `DistillContext`，distill adapter 接受 `distill_context` 参数；mutator 形态名（`delete / update / purge`）通过 `__getattr__` 抛 `DistillReadOnlyError(method, hint)`。
- **search 按 memory_type 过滤**：MCP `search_memory` / REST `/search` / CLI `harness-mem search` 三端新增 `memory_type` 列表过滤（`episodic | semantic | procedural`，OR 语义；`None / []` 不过滤）。MCP / REST 对非法值返回 422-class 错误，CLI stderr 提示并以非零退出码失败。
- **doctor 错误码**：`HM-101 wake bucket quotas must sum to 1.0` 与 `HM-102 wake bucket quota out of range` 加入 `docs/error-codes.md`；`harness-mem doctor` 在 `[wake]` 配置非法时立即报告。
- **storage 索引列**：`memory_entries` 表新增 `memory_type TEXT NOT NULL DEFAULT 'semantic'` 列（`_COLUMN_MIGRATIONS` 自动迁移），让 search 可以走 SQL `WHERE` 过滤而不是 blob 后置筛选。
- **CLI distill `--auto-confirm` 兼容路径**：`harness-mem distill --auto-confirm` 在产出后立即把 pending 候选转 accepted，保留 v1.6.0 的 `ingest -> distill -> wake` dogfood 流。

### Changed

- **distill 默认产 pending（breaking）**：`harness-mem distill` 默认输出 `(status: pending)`，不再立即进入 accepted 列表。`wake-up` 与默认 `search` 因 `status="accepted"` 过滤天然看不到 pending 记忆，需要先 `confirm_memory_entry`/`--auto-confirm`。
- `ClaudeCodeAdapter.distill_session / distill_relation_facts` 接受可选 `distill_context: DistillContext`；当传入时所有写动作走候选层，旧 `backend` 路径保留为兼容入口。
- `read_api.search_memory` / `LocalStructuredStore.search_memory_entries` / `StructuredStore` Protocol 新增 `memory_type` 参数。

### Notes

- v1.6.1 不动 retrieval 算法；理论上 LongMemEval 五维 R@5 不应回退（hybrid (real) baseline 见 `docs/benchmark/v160-baseline.md`）。本切片提交前实测见 `benchmarks/results/v161-baseline-hybrid.json` 与 `docs/benchmark/v161-bucket-budget-impact.md`。
- 持久化向量索引（sqlite-vec）+ embedding 模型 shootout 推迟到 v1.6.2；vision 文档与 `roadmap-v16x.md` 已划清边界。
- `DistillContext` 不暴露 `auto_confirm_pending` 这类 mutator——`--auto-confirm` 的实际写入由 `harness_mem.commands.distill._confirm_pending_outputs` 通过 `update_*_status` mutator 完成；这是 CLI 层的"运维出口"，而非 distill 路径的"绕过候选层"。

---

## [1.6.0] — 2026-05-17

**主题：测量地基 + 记忆分型 schema（非破坏性 baseline 切片）**

v1.6.x 三切片路线的第一刀。本切片只动 schema 与测量层，不动 retrieval / wake-up / distill 行为；为 v1.6.1（wake-up bucket budget + distill 只读边界）与 v1.6.2（sqlite-vec 持久化向量 + embedding 模型 shootout）打地基。

完整决策与 baseline 见 [`docs/roadmap-v16x.md`](docs/roadmap-v16x.md) 与 [`docs/benchmark/v160-baseline.md`](docs/benchmark/v160-baseline.md)。

### Added

- **`MemoryEntry.memory_type` 字段**：新增 `Literal["episodic", "semantic", "procedural"]`，默认 `semantic`。`from_dict` 兼容老数据：缺字段时按 `category` 自动派生（`architecture / convention / api / bug / decision -> semantic`，否则 `episodic`）。`procedural` 字面量保留供 v1.8 使用，v1.6.0 不主动产生。
- **`MemoryType` 类型别名**：从 `harness_mem.core.schemas` 顶层导出。
- **`harness-mem maintenance assign-memory-types`**：一次性幂等 backfill 命令，把 `memory_type` 持久化到老 `MemoryEntry` JSON blob。`--dry-run` 默认；`--apply` 落盘；连续 `--apply` 后再次 `--dry-run` 显示 0 条变更。
- **search payload 暴露 `memory_type`**：CLI / MCP `search_memory` / REST `/search` 三端在 memory entry 行返回 `memory_type` 字段（只读，v1.6.1 才引入按类型 filter）。CLI 输出格式从 `[category]` 改为 `[category/memory_type]`。
- **LongMemEval 五维评分作为一等公民**：`harness_mem.tools.longmemeval` 顶部声明 `LONGMEMEVAL_QUESTION_TYPES` 常量（6 个登记维度）；CLI 输出 `PER-TYPE RECALL` 段；JSON 报告含 `per_type` 字典；未登记维度产生 `UserWarning`，不阻断评测。
- **v1.6.0 LongMemEval baseline**：`docs/benchmark/v160-baseline.md` 记录 `fts / hybrid (synthetic) / hybrid (real)` 三种 mode 在 6 个维度的 R@5；`hybrid (real) avg = 0.953`，精确复现 v1.5.2/v1.5.3 数字。`docs/benchmark/longmemeval-five-dimensions.md` 解释每个维度含义与 v1.6.x 各切片预期。
- **v1.6.x roadmap**：`docs/roadmap-v16x.md` 写明三切片切分、决策路径、不回退判定规则。

### Changed

- `docs/README.md` 登记 `roadmap-v15x` / `roadmap-v16x` / `roadmap-vision-v16-v18` 三份 roadmap，并更新 benchmark 目录条目。
- `tests/conftest.py` 把 `maintenance` 模块加入 `DEFAULT_DATA_DIR` monkeypatch 列表。

### Notes

- v1.6.0 是非破坏性切片：v1.5.3 用户升级后不需要任何数据迁移。`MemoryEntry.from_dict` 在加载时即 derive `memory_type`，`maintenance assign-memory-types` 是把它显式持久化到 JSON 的运维入口，不是必需步骤。
- LongMemEval 总分不再作为单一 KPI——v1.6.x 起所有 retrieval 改动必须贴五维对比表。详见 `docs/benchmark/longmemeval-five-dimensions.md` "为什么单一总分会误导" 段。
- v1.6.2 默认 embedding 模型不在启动前预选，由 shootout 数据驱动；详见 `docs/roadmap-v16x.md` "已决策 3"。

---

## [1.5.3] — 2026-05-17

**主题：发布闭环与归档增量化**

### Added

- **Codex archive 增量 cursor**
  - `CodexArchiveAdapter` 现在按 `mtime_ns + size_bytes` 持久化 cursor。
  - `harness-mem ingest codex-archive` 支持默认增量扫描与 `--full-rescan` 显式回扫。
  - 已补 `tests/cli/test_ingest_codex_archive.py` 覆盖缺目录、增量追加、full-rescan 去重三条路径。
- **PyPI 发布链路**
  - 新增 tag 触发的 `.github/workflows/publish.yml`，构建 wheel + sdist,执行 `twine check`，并在发布前 smoke install 两种发行物。
- **Doctor 错误码目录**
  - `harness-mem doctor` 现在输出 `code: HM-xxx` 与对应修复命令。
  - 新增 `docs/error-codes.md` 作为稳定对照表。

### Changed

- `README.md` 现在把 `pip install harness-mem` 作为默认安装入口，保留 editable install 作为仓库开发路径。
- `pyproject.toml` 增加 `dev` optional dependency，并把 `README.md` / `docs/error-codes.md` 纳入发行物元数据。
- `test-matrix.yml` 改为使用仓库标准验证栈：`pytest` + `mypy` + `ruff`。
- **MCP `search_memory` 工具签名调整**：`query` 提到第一位、`project_name` 改为可选关键字参数（`scope=all` 时省略即可）。MCP 客户端按 `input_schema` 字段名传参不受影响；任何按位置传参的内部脚本必须改成关键字传参。
- **MCP `tool_search_memory` 内部合并 event loop**：之前每次请求会执行 4 次 `asyncio.run`（search / search_relation_facts / 循环 touch / build context map），现在合并为单次 `asyncio.run` 调用 `_gather_search_payload`。Backend 连接池在一次请求内保持活跃。返回字段不变。
- **`HybridSearchLayer` 的 RRF 参数提到模块级常量**：`DEFAULT_RRF_K / DEFAULT_FTS_WEIGHT / DEFAULT_VECTOR_WEIGHT / DEFAULT_FTS_CONFIDENCE_EXPONENT / DEFAULT_VECTOR_CONFIDENCE_EXPONENT`，并在源码注释里诚实记录这些值是经验值而非 ablation 结果，留待 v1.6 embedding 升级时一并复评。

### Notes

- v1.5.2 的 `hybrid` P95 latency `625.17ms` 是 LongMemEval 全量带 vector encode 的端到端数据，**与 v1.5.1 baseline 文档里 wake-up 数据加载 `25.57ms` 的 P95 不可直接相比**。
- v1.5.2 引入的 Porter-stem FTS fallback 会把 token 用前缀匹配扩散（`auth` -> `auth*` 命中 `auth_handler / auth_handler_v2`），这是 LongMemEval session_id-only 评分体系下不可见的 precision 副作用。代码符号搜索 / 完全匹配场景请显式 `mode="fts"` 并配合精确查询；细节见 `docs/benchmark/v152-recall-failure-analysis-stemfallback.md`。

## [1.5.0] — 2026-05-16

**主题：AI-led Memory Candidate Loop (AI 记忆候选闭环)**

本版本正式确立了 harness-mem 的核心协作协议，实现了“历史归档集成”与“AI 原生工作流”的深度统一。

| 角色 | 动作与职责 | 最佳技术载体 |
| :--- | :--- | :--- |
| **AI（操作者/后端）** | 批量读取旧 Session，用强大的 LLM 提炼知识，过滤废话，生成结构化记忆。 | Skill (如 `session-distill`) |
| **候选写入能力** | 在显式 distill、Skill 流程或用户明确要求记录时，把规则/知识写入候选层。 | MCP (调用 `suggest_rule` / `suggest_memory_entry`) |
| **人（审查者）** | 不看几万字的废话，只看 AI 提炼好的结论，点确认 (Confirm) 或拒绝 (Reject)。 | CLI (`confirm` / `reject`) |
| **AI（消费者/前端）** | 在新 Session 中通过 Wake/Search 读取之前人确认过的记忆，应用到任务。 | MCP (`search_memory`) |

### Added

- **Codex 历史归档集成 (Legacy Activation)**
  - 移植了 OneDrive 版 `session-distill` 的高精度解析算法，支持 `rollout-*.jsonl` 格式。
  - 新增 `CodexArchiveAdapter` 适配器，支持 `harness-mem ingest codex-archive`。
  - 自动清洗 IDE 上下文模板、转义字符及 `<turn_aborted>` 标记。
- **Repo-local Codex plugin wrapper**
  - Added `plugins/harness-mem/` with a Codex plugin manifest, harness-mem skill, MCP server config, and PowerShell install/doctor helpers.
  - Added `.agents/plugins/marketplace.json` entry for local plugin discovery.

### Removed
- **Temporal Bias feature** — removed `--temporal-bias` CLI flag, `temporal_bias` MCP/REST API parameter, and all related code. Benchmark evidence showed it was ineffective.

### Changed
- **文档体系大重构**
  - 重写 `best-practices.md`：转向“AI 记忆候选闭环”与“候选层”核心机制。
  - 重写 `session-distill` Skill 定义：废弃本地文件 Packet 流，拥抱 Python 原生与 MCP 接口。
  - 生成 `retrospective-v13-v14.md`：归档“八方评审”结论，确立架构演进真值。
- **检索与 Ingest 体验硬化**
  - 增量 ingest 现在使用 `last_ingest_session_id` 作为精准游标。
  - search / MCP 显示实际检索模式（requested vs effective），显式展示 fallback。
  - `purge` 增强：支持 `-p/--project`，修复 UTC 时间戳比较崩溃及 `compacted` 列缺失问题。
- **Parity & API**
  - `search_memory` MCP 工具支持 `mode` 参数。
  - REST API 稳定性增强，修复 `/search` 的项目隔离与异步初始化。

### Fixed
- **真实项目体验**
  - `ingest claude-code` 支持通过 `cwd` 识别项目根目录，适配 Unity 等复杂工程布局。
  - Unity profile 自动探测（C#、ProjectVersion、manifest 等）。
  - Claude observation 摘要逻辑优化，保留上下文首尾。
  - FTS 索引中英混排 Token 分词优化。

---

## [1.2.0] — 2026-04-25

### Added

- **`wake-up` explainability**
  - 每块 section 标题追加来源注释：`## Project Profile  (source: profile, ~N chars)`
  - 空数据区块显示 `(source: {category}, empty)` 而非跳过，保持结构一致

- **Compact Guard（提示文字）**
  - `doctor` 和 `wake-up` 在 L3/L4+ 时打印 Compact suggestion
  - 建议运行 `harness-mem ds --category bug` / `decision`

- **`profile --edit`（merge 策略）**
  - 交互式编辑 profile 字段：`description`、`stacks`、`key_files`、`conventions`
  - 新值覆盖对应字段，其他字段保留

---

## [1.0.1] — 2026-04-24

**定位**：v1 稳定化 / 体验收口版本。

### Added
- **`quickstart` 命令**：一步完成初始化、活动项目设置、最近 session 发现。
- **`doctor` 命令**：状态感知决策树建议。
- **Active project 记忆**：不必重复指定 `--project`。

---

## [1.0.0] — 2026-04-23

**定位**：v1 Core MVP。

### Added
- **双层记忆底座**：Verbatim (Observation) + Structured (Entry/Rule/Handoff)。
- **Adapter**：Claude Code + Codex。
- **MCP Server**：完整读取/写入工具链。
