# Roadmap: harness-mem v2.9

> 状态：v2.9.0–v2.9.60 已完成。
>
> 主题：PRD sync 起步，随后扩成 maintenance / triage / truth-sync release train。
> v2.9 从 `/hm:prd-sync` 这一条 candidate-only maintenance surface 开始，随后逐步
> 收口了 `/hm:status`、plugin doctor helper、maintenance CLI collateral、
> reflection/config truth、以及 wake / distill / status 等高可见入口的 current-truth
> sync。

---

## 目标

v2.9 的起点是把当前 repo 里已经存在的 `prd-sync` 半成品脚本收成正式维护面：

- 它扫描 `bundled` packets
- 它识别 PRD / roadmap / scope / architecture 一类关键词
- 它可以在 `prd-distilled/` 下生成候选 markdown

因此 v2.9.0 的第一目标是：

- 把 `/hm:prd-sync` 收成正式的 candidate-only maintenance entry
- 明确 dry-run default 与 `--apply` 只写 candidate markdown 的边界

后续 v2.9.1+ 的版本线则沿着同一条思路继续推进：

- 把 `/hm:status`、plugin doctor helper 等高可见维护/分诊入口收成正式 surface
- 把 CLI / shell completion / MCP / README / telemetry / user-test packet 等
  collateral 同步到已 shipped 的 maintenance-only truth
- 把 `roadmap-v24`、`roadmap-status`、`README`、`AGENTS`、`best-practices`、
  `roadmap-v22x` 等高可见文档持续回写到当前 shipped truth

也就是说，`v2.9` 已不再只是 “PRD sync candidate surface” 这一条单独切片，而是一个
围绕 maintenance / triage / truth-sync 收口的 release train。

---

当前 repo 最早在 `tools/session-distill/bin/session-distill.py` 里放了一个
`prd-sync` 命令：
- 它会扫描 `bundled` packets
- 它会识别 PRD / roadmap / scope / architecture 一类关键词
- 它可以在 `prd-distilled/` 下生成候选 markdown

但这块能力仍然停留在“脚本里有命令”的阶段，还没有正式产品面真值：

1. 没有 slash / 自然语言入口说明。
2. 没有 OpenSpec contract。
3. 没有 focused tests。
4. 没有清晰边界来说明它只能产 candidate，不能直接改正式文档。

v2.9 的目标不是扩新记忆类型，而是把这条现有维护面收成正式、可验证的
candidate surface。

---

## Scope

| 领域 | v2.9 决策 |
|---|---|
| Entry surface | 新增 `/hm:prd-sync [--apply]` 作为维护入口 |
| Input boundary | 只读取 session-distill manifest 中 `bundled` packet |
| Default behavior | 默认 dry-run，只预览命中的 packet 和 topic |
| Apply behavior | `--apply` 只写 `prd-distilled/*.md` candidate 文件 |
| Mutation boundary | 不直接改 PRD、roadmap、knowledge-base 或 confirmed truth |
| Workflow position | 属于 maintenance / review bridge，不属于 `/hm:distill` 主链 |

---

## v2.9.0：PRD Sync Candidate Surface

**用户故事**：当 bundled packets 里已经出现了 PRD、roadmap、scope、architecture
类讨论时，Agent 可以先生成一份 candidate PRD sync note，让后续产品文档整理有
依据，但不会越权直接改正式 PRD 或 roadmap。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `/hm:prd-sync` entry contract | 成为正式维护入口，而不是隐藏脚本 |
| P0 | dry-run default | 默认只预览，不写文件 |
| P0 | candidate-only apply | `--apply` 只写 `prd-distilled/*.md` |
| P1 | projectless maintenance boundary | 不要求项目 cwd 解析才能运行 |
| P1 | focused regression tests | 覆盖 no bundle / dry-run / apply / bundled-only scanning |

### 当前状态（2026-06-02）

- 已完成 `openspec/changes/archive/2026-06-02-v290-prd-sync-candidate-surface/`。
- `/hm:prd-sync [--apply]` 已进入 README、plugin command、session-distill
  references 与 OpenSpec 主 contract。
- `prd-sync` 现在明确是 projectless maintenance entry：
  - 默认 dry-run
  - `--apply` 只写 `prd-distilled/*.md`
  - 不直接改正式 PRD、roadmap、knowledge-base 或 confirmed truth
- 已补 focused tests，覆盖：
  - no bundled packets
  - dry-run 不写文件
  - apply 只写 candidate markdown
  - 只扫描 `bundled` sessions

## v2.9.1：Status Triage Surface

**用户故事**：用户运行 `/hm:status` 时，看到的是一个稳定的、只读的项目记忆分诊入口，而不是不同文档各说各话的“也许是 doctor，也许是 MCP status”的混合面。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `/hm:status` contract | 成为正式 read-only triage 入口 |
| P0 | MCP triage hints | `get_project_status` 返回 `phase` / `suggested_slash` / `reason` |
| P0 | review-only hint boundary | pending candidates 只追加 repair hint，不把 `/hm:review` 升成主 happy path |
| P1 | doc alignment | plugin README、slash command、roadmap 与真实 MCP 行为一致 |

### 当前状态（2026-06-02）

- 已完成 `openspec/changes/archive/2026-06-02-v291-status-triage-surface/`。
- `/hm:status` 现在正式收束成 read-only triage surface。
- MCP `get_project_status` 现在会返回：
  - `phase`
  - `suggested_slash`
  - `reason`
  - 可选 `repair_hint` / `repair_reason`
- triage 语义锁定为：
  - empty project → `/hm:distill`
  - ready project → `/hm:wake`
- pending candidates → 只作为 repair-only `/hm:review` hint

## v2.9.2：Plugin Doctor Helper Integrity

**用户故事**：repo-local plugin 提供的 `doctor.ps1` 应该是一个稳定的本地验证入口，而不是在成功跑完 doctor 之后又因为调用了已移除的 CLI `status` 子命令而自己报错。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | helper integrity | `doctor.ps1` 只调用当前受支持的 maintenance CLI surface |
| P0 | `-Wake` hint-only | `-Wake` 只补充 IDE wake 提示，不重引入 CLI `status/wake` |
| P1 | script smoke | 在隔离 `HOME/USERPROFILE` 下脚本能成功跑通 |

### 当前状态（2026-06-02）

- 已完成 `openspec/changes/archive/2026-06-02-v292-plugin-doctor-helper-integrity/`。
- `doctor.ps1` 不再调用不存在的 `python -m harness_mem.cli status`。
- `-Wake` 现在是 hint-only：会在 doctor 之后输出 `/hm:wake` 的 IDE 用法。
- 已补脚本级 smoke，覆盖：
  - 隔离 home 环境下脚本成功返回
  - 不再出现 `invalid choice: 'status'`

## v2.9.3：CLI Maintenance Surface Truth

**用户故事**：当维护者查看 `harness-mem --help` 或回读主 CLI spec 时，应该看到
同一份 maintenance-only 真值，而不是实现和 OpenSpec 对 `config` /
`integration` 是否属于正式 CLI surface 各说各话。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | top-level CLI truth sync | 主 `cli` spec 的命令集合与真实 `--help` 一致 |
| P0 | `config` namespace contract | 明确 `get/set/list/validate` 属于 maintenance config 面 |
| P0 | `integration` namespace contract | 明确 hook 安装器属于 maintenance integration 面 |
| P1 | release writeback | roadmap / status / changelog / version 与 v2.9.3 一致 |

### 当前状态（2026-06-02）

- 已完成 `openspec/changes/archive/2026-06-02-v293-cli-maintenance-surface-truth/`。
- 主 `openspec/specs/cli/spec.md` 现在与真实 `harness-mem --help` 对齐：
  - top-level command set 包含 `config` 与 `integration`
  - `config` 明确是 TOML 配置维护命名空间
  - `integration` 明确是 host-entry hook 安装命名空间
- 该切片只做 current-truth sync，不引入新的业务 CLI 子命令，也不恢复
  `wake/search/distill` 等日常 memory CLI 面。

---

## Non-Goals

- 不让 `prd-sync` 直接编辑正式 PRD 或 roadmap 文档。
- 不让 `prd-sync` 写 confirmed rule / memory / relation / skill truth。
- 不把 `prd-sync` 做成 `/hm:distill` 主链的一部分。
- 不引入新的 daemon、scheduler 或后台自治文档同步。

---

## 与既有版本线的关系

| 能力 | 依赖 |
|---|---|
| `/hm:distill` 主链 | `docs/roadmap-v22x.md` |
| host-triggered reflection / doctor | `docs/roadmap-v24.md` |
| shared skills / controlled activation | `docs/roadmap-v27.md` |
| session-distill maintenance family | `docs/roadmap-v28.md` |

v2.9 是对 session-distill maintenance family 的补片：从 bundled packet 到
产品文档整理之间，补一个 candidate-only 的桥，而不是开启新的自治写面。

## v2.9.4：Stale CLI Surface Guard Sync

**用户故事**：当仓库用 focused regression test 守护“用户文档不要教已移除的日常 CLI”时，测试本身也应该描述当前真实 maintenance surface，而不是停留在 `config/integration` 发版之前的旧口径。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | stale-surface guard sync | `tests/test_stale_cli_surface.py` 的注释与 allowlist 对齐当前 CLI truth |
| P0 | maintenance allowlist | `config` / `integration` 被视为受支持的 maintenance verbs，而不是未来误报源 |
| P1 | release writeback | roadmap / status / changelog / version 与 v2.9.4 一致 |

### 当前状态（2026-06-02）

- 已完成 `openspec/changes/archive/2026-06-02-v294-stale-cli-surface-guard-sync/`。
- `tests/test_stale_cli_surface.py` 现在与当前 maintenance-only CLI truth 对齐：
  - 注释里的 command set 已包含 `config` / `integration`
  - `ALLOWED_MAINTENANCE` 已包含 `config` / `integration`
  - 该测试继续只禁止被移除的 daily-memory verbs，不阻止已支持的 maintenance docs
- 该切片不改 runtime surface，只修 guardrail/test truth 与 release docs。

## v2.9.5：Shell Completion Maintenance Truth

**用户故事**：当维护者启用 `harness-mem --completion <shell>` 时，shell 提示应该和真实 CLI 一样包含 `config` / `integration`，而不是继续暴露一套更早期的 maintenance surface。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | top-level completion sync | bash / zsh / fish completion 包含 `config` / `integration` / `qs` |
| P0 | namespace action completion | `config` / `integration` 的二级 action 能补全 |
| P1 | focused regression tests | completion 输出和 CLI `--completion` 都有回归覆盖 |

### 当前状态（2026-06-02）

- 已完成 `openspec/changes/archive/2026-06-02-v295-shell-completion-maintenance-truth/`。
- `harness_mem.shell_completion` 现在和当前 maintenance-only CLI truth 对齐：
  - top-level completion 已包含 `config` / `integration` / `qs`
  - `config` action completion 已包含 `get` / `set` / `list` / `validate`
  - `integration` action completion 已包含 `install-cursor-hook` / `install-claude-hook`
- 已补 focused tests，覆盖：
  - bash / zsh / fish 生成脚本
  - `python -m harness_mem.cli --completion bash`

## v2.9.6：Maintenance Surface Collateral Sync

**用户故事**：当维护者阅读 MCP 主 spec 或拿 `docs/v2-user-test-packet.md` 做用户面验收时，不应该再看到一份停留在 `config/integration` 发版之前的旧 maintenance CLI 口径。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | MCP spec sync | `openspec/specs/mcp/spec.md` 对齐当前 maintenance CLI surface |
| P0 | user-test packet sync | `docs/v2-user-test-packet.md` 的允许维护命令包含 `config` / `integration` |
| P1 | release writeback | roadmap / status / changelog / version 与 v2.9.6 一致 |

### 当前状态（2026-06-02）

- 已完成 `openspec/changes/archive/2026-06-02-v296-maintenance-surface-collateral-sync/`。
- 剩余高可见 collateral 已对齐当前 maintenance CLI truth：
  - `openspec/specs/mcp/spec.md` 现在包含 `qs` / `config` / `integration`
  - `docs/v2-user-test-packet.md` 现在把 `config` / `integration` 视为允许的维护类 CLI 命令
- 该切片不改 runtime surface，只收束残留的 spec / user-test 口径。

## v2.9.7：README And Telemetry Maintenance Truth

**用户故事**：当维护者读 README 架构图或 telemetry 主 spec 时，不应该再看到一套比真实 CLI 更旧的 maintenance command summary。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | README maintenance summary sync | README 架构图里的 maintenance console 包含 `config` / `integration` |
| P0 | telemetry spec sync | telemetry 主 spec 的 CLI coverage 包含 `qs` / `config` / `integration` |
| P1 | status doc cleanup | `docs/roadmap-status.md` 不再保留重复 summary 行 |

### 当前状态（2026-06-02）

- 已完成 `openspec/changes/archive/2026-06-02-v297-maintenance-surface-readme-and-telemetry-sync/`。
- 剩余高可见 maintenance collateral 已对齐当前 truth：
  - README 的 maintenance-console summary 已包含 `config` / `integration`
  - telemetry 主 spec 已包含 `qs` / `config` / `integration`
  - `docs/roadmap-status.md` 的重复 summary 行已移除
- 该切片不改 runtime surface，只做 README / spec / status writeback。

## v2.9.8：Maintenance Surface Collateral Guard

**用户故事**：既然 README、MCP spec、telemetry spec 和 user-test packet 都已经同步到了当前 maintenance console，就应该有一个 focused regression test 把这份真值锁住，而不是每次靠人工再扫一遍。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | collateral truth guard | README / MCP spec / telemetry spec / user-test packet 都被 focused test 覆盖 |
| P1 | release writeback | roadmap / status / changelog / version 与 v2.9.8 一致 |

### 当前状态（2026-06-02）

- 已完成 `openspec/changes/archive/2026-06-02-v298-maintenance-surface-collateral-guard/`。
- 新增 `tests/test_maintenance_surface_collateral.py`，覆盖：
  - README maintenance-console summary
  - MCP spec maintenance surface summary
  - telemetry spec maintenance surface summary
  - v2 user-test packet 的允许维护命令 summary
- 该切片不改 runtime surface，只给现有 collateral truth 加回归护栏。

## v2.9.9：Reflection Project-Root Resolution

**用户故事**：当 host entry 之外的共享 reflection business command 以
`project_root=None` 被调用时，如果 repo 已经能通过 commands-layer lookup 定位到，
job 记录里就不应该退化成调用方 cwd；只有在确实找不到已知 root 时，cwd 才是最后兜底。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | known-root-first resolution | `reflection_once(...)` 先尝试 `find_project_root(project_name)` |
| P0 | cwd final fallback | 没找到已知 root 时仍保留 cwd 兜底 |
| P1 | focused regression tests | 覆盖 known-root path 和 no-known-root fallback |

### 当前状态（2026-06-02）

- 已完成 `openspec/changes/archive/2026-06-02-v299-reflection-project-root-resolution/`。
- `harness_mem.commands.reflection_jobs.reflection_once(...)` 现在会：
  - 优先使用 commands-layer 的已知 project root lookup
  - 仅在 lookup 失败时回退到 cwd
- 已补 focused tests，覆盖：
  - `project_root=None` 且能找到已知 root
  - `project_root=None` 且找不到已知 root

## v2.9.10：Worker-Mode Truth Sync

**用户故事**：当维护者按 v2.4 roadmap 或 operator doc 配置 host-triggered
reflection 时，不应该再被旧文档误导去写 `worker.mode = "daemon"`，因为当前 loader
和 tests 只承认 `off|on`。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap truth sync | `roadmap-v24` / `roadmap-status` 不再把 `worker.mode` 写成 `daemon` |
| P0 | operator doc sync | `docs/cli/v2.4.md` 对齐当前 `off|on` gate |
| P1 | focused regression guard | docs truth 绑定 `_RECOGNIZED_KEYS` 中的 `worker.mode` |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2910-worker-mode-truth-sync/`。
- `worker.mode` 当前真值已收束成：
  - 允许值只有 `off` / `on`
  - `on` 只是 non-default config gate
  - 当前 runtime 仍无默认 always-on daemon 安装器或后台主路径
- 已补 focused regression test：`tests/test_worker_mode_truth.py`

## v2.9.11：Scheduler Trigger Truth Sync

**用户故事**：当维护者回看 v2.4 配置文档时，不应该再被 `triggers.scheduler = "cron"`
这类旧口径误导，因为当前 loader 和 tests 只承认 `off|on`。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap truth sync | `roadmap-v24` 不再把 `triggers.scheduler` 写成 `off|cron` |
| P0 | operator doc sync | `docs/cli/v2.4.md` 明确 `on` 只是 scheduler/cron gate |
| P1 | focused regression guard | docs truth 绑定 `_RECOGNIZED_KEYS` 中的 `triggers.scheduler` |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2911-scheduler-trigger-truth-sync/`。
- `triggers.scheduler` 当前真值已收束成：
  - 允许值只有 `off` / `on`
  - `on` 只是 scheduler/cron host trigger gate
  - 当前 runtime 不内建 cron expression schema 或 schedule installer
- focused regression guard 已扩展到 scheduler trigger truth。

## v2.9.12：Distill-Mode Truth Sync

**用户故事**：当维护者回看 v2.4 配置文档时，不应该再被 `notify_only` /
`embedded_llm` 这类旧设计项误导，因为当前 loader 和 tests 只承认
`defer_to_agent | inline | worker`。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap truth sync | `roadmap-v24` 的 `distill.mode` 表对齐 shipped values |
| P0 | release/status sync | `roadmap-status` / `CHANGELOG` / `v29` 说明当前 truth |
| P1 | focused regression guard | docs truth 绑定 `_RECOGNIZED_KEYS` 中的 `distill.mode` |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2912-distill-mode-truth-sync/`。
- `distill.mode` 当前真值已收束成：
  - 允许值只有 `defer_to_agent` / `inline` / `worker`
  - `defer_to_agent` 仍是默认 shipped path
  - 当前 runtime 仍未把 `inline` / `worker` 扩成默认 LLM/daemon 主路径
- focused regression guard 已扩展到 `distill.mode` truth。

## v2.9.13：Host-Entry Module Truth Sync

**用户故事**：当维护者回看 v2.4 roadmap 里的 hook/host trigger 示例时，不应该再看到
`harness_mem.<host_entry>` 这样的占位符、`python -m harness_mem.host` 这种旧模块名，
或把 `reflection_once` 写成 host-entry 位置参数的旧调用形式，因为当前 shipped
runtime、hook 模板和 operator doc 都只承认 `python -m harness_mem.host_entry`
加 flags 的调用方式。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap truth sync | `roadmap-v24` 的 host-entry 示例改为 shipped module path + flags |
| P0 | placeholder/old-path removal | 不再保留 `harness_mem.<host_entry>`、`harness_mem.host`、`host_entry reflection_once` |
| P1 | focused regression guard | current-truth docs 回流到旧 host-entry 口径时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2913-host-entry-module-truth-sync/`。
- `docs/roadmap-v24.md` 现在统一使用：
  - `python -m harness_mem.host_entry`
  - `--project-root ...`
  - `--source ide_hook`
- 已补 focused regression test：`tests/test_host_entry_module_truth.py`

## v2.9.14：v2.4 Config And Job Truth Sync

**用户故事**：当维护者回看 v2.4 roadmap 的 config merge 和 queue model 段落时，
不应该再被规划期残留误导成“loader 会解析 `project_name` / `active_project.txt`”
或“runtime 里还有一个单独的 `ReviewJob` schema”，因为当前 shipped truth 并不是这样。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | config-loader truth sync | `roadmap-v24` 只描述 `load_merged_config()` 实际认的四个 key |
| P0 | single-job-model truth sync | `roadmap-v24` 只描述 `ReflectionJob`；`review` 仅为 phase |
| P1 | focused regression guard | config/job model 旧口径回流时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2914-v24-config-and-job-truth-sync/`。
- `docs/roadmap-v24.md` 现在明确：
  - merged-config loader 的 recognized keys 只有
    `triggers.after_agent` / `triggers.scheduler` / `distill.mode` / `worker.mode`
  - `project_name` 和 `active_project.txt` 不属于这个 loader contract
  - 当前 queue model 只有 `ReflectionJob`；`review` 只是 phase
- 已补 focused regression test：`tests/test_v24_config_and_job_truth.py`

## v2.9.15：Wake Entrypoint Truth Sync

**用户故事**：当维护者回看 repo-local `/hm:wake` 命令和 `harness-mem` skill 时，
不应该再被旧 prompt 误导成“wake 默认要手工拼四个低层读工具”，因为当前 shipped
truth 已经是一等 MCP `wake` surface，并且 compact renderer 与 skill hints 都挂在它上面。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `/hm:wake` command truth sync | slash 文档默认走 `wake(project_name=<project>)` |
| P0 | skill wake guidance sync | repo-local skill 默认走 `get_project_status` + `wake(...)` |
| P1 | focused regression guard | wake 文档/skill 回流到旧 low-level choreography 时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2915-wake-entrypoint-truth-sync/`。
- `plugins/harness-mem/commands/hm/wake.md` 现在明确：
  - 默认走 MCP `wake(project_name=<project>)`
  - compact generated summary 走 `renderer="compact"`
  - procedural hints 走 `include_skill_hints=true`
- `plugins/harness-mem/skills/harness-mem/SKILL.md` 的 wake-up 流程也已同步
- 已补 focused regression test：`tests/test_wake_entrypoint_truth.py`

## v2.9.16：Best-Practices Wake Truth Sync

**用户故事**：当维护者回看 `docs/best-practices.md` 的 runtime 工具表和 wake-up
章节时，不应该再看到抽象的“调用 wake 逻辑”写法，而应该直接看到当前 shipped 的一等
MCP `wake` surface，以及 compact / skill-hint 这两个显式 opt-in 扩展。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | tool catalog sync | best-practices 的读取工具表包含 `wake` |
| P0 | wake-up section sync | best-practices 明确默认走 `wake(project_name=<project>)` |
| P1 | focused regression guard | best-practices 回流到旧抽象写法时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2916-best-practices-wake-truth-sync/`。
- `docs/best-practices.md` 现在明确：
  - `wake` 是一等读取工具
  - 默认走 MCP `wake(project_name=<project>)`
  - `renderer="compact"` / `include_skill_hints=true` 是显式 opt-in
- 已补 focused regression test：`tests/test_best_practices_wake_truth.py`

## v2.9.17：Distill Auto-Review Entrypoint Truth Sync

**用户故事**：当维护者回看 `/hm:distill` 命令文档、repo-local skill 或 MCP 主 spec
示例时，不应该再被“先 `list_candidates` 再逐条 `confirm_*` / `reject_*`”的旧写法误导，
因为当前 shipped distill review truth 已经是一等 `auto_review_candidates(apply=true)`
shared policy。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `/hm:distill` truth sync | slash 文档默认走 `auto_review_candidates(project_name=<project>, apply=true)` |
| P0 | repo-local skill sync | skill 不再保留 “when available” 式旧回退 |
| P0 | MCP example sync | MCP 主 spec 的 distill 示例直接使用 `auto_review_candidates` |
| P1 | focused regression guard | distill 文档与 skill 回流到手工 per-item review 时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2917-distill-auto-review-entrypoint-truth-sync/`。
- `/hm:distill` 文档现在明确：
  - 默认 review surface 是 MCP `auto_review_candidates(project_name=<project>, apply=true)`
  - 最终摘要以 `auto_review_candidates` 返回的 canonical counters 和 `applied_decisions` 为准
- repo-local `harness-mem` skill 不再把手工 `list_candidates` + `confirm_*` / `reject_*`
  写成默认 shipped fallback
- 已补 focused regression test：`tests/test_distill_auto_review_truth.py`

## v2.9.18：Status Entrypoint Truth Sync

**用户故事**：当维护者回看 `/hm:status` 命令文档或 MCP 主 spec 的 status 示例时，
不应该再被“先 `get_project_profile` / `list_candidates` / `timeline` 再自己拼状态”的旧写法误导，
因为当前 shipped triage truth 已经是一等 `get_project_status` surface，会直接返回
`phase`、`suggested_slash`、`reason` 和可选 repair hint。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `/hm:status` truth sync | slash 文档默认走 `get_project_status(project_name=<project>)` |
| P0 | MCP status example sync | MCP 主 spec 示例直接展示 `phase` / `suggested_slash` / `reason` / repair hint |
| P1 | focused regression guard | status 文档回流到手工拼低层读工具时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2918-status-entrypoint-truth-sync/`。
- `/hm:status` 文档现在明确：
  - 默认 triage surface 是 MCP `get_project_status(project_name=<project>)`
  - 只有用户明确追问 provenance 或旧 pending 细节时，才继续下钻 `timeline` / `list_candidates`
- MCP 主 spec 的 status 示例现在直接展示：
  - `phase`
  - `suggested_slash`
  - `reason`
  - 可选 `repair_hint` / `repair_reason`
- 已补 focused regression test：`tests/test_status_entrypoint_truth.py`

## v2.9.19：Best-Practices Auto-Review Truth Sync

**用户故事**：当维护者回看 `docs/best-practices.md` 的候选层说明、角色表和工具表时，
不应该再被“`/hm:distill` 默认先 `list_candidates` 再逐条 `confirm_*` / `reject_*`”
的旧写法误导，因为当前 shipped distill review truth 已经是一等
`auto_review_candidates(project_name=<project>, apply=true)` shared policy。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | best-practices auto-review sync | `best-practices` 把 `auto_review_candidates` 写成默认 distill review surface |
| P0 | tool catalog sync | 管理工具表把 `auto_review_candidates` 视为默认 review tool，`list_candidates` 降为 drilldown/recheck |
| P1 | focused regression guard | best-practices 回流到 per-item review 旧写法时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2919-best-practices-auto-review-truth-sync/`。
- `docs/best-practices.md` 现在明确：
  - `Memory Expert` 默认复用 `auto_review_candidates`
  - `Gardener` 在 `/hm:distill` 同一轮调用 `auto_review_candidates(project_name=<project>, apply=true)`
  - `list_candidates` 只保留给显式 review drilldown 或用户纠错流
- 已补 focused regression test：`tests/test_best_practices_auto_review_truth.py`

## v2.9.20：README Distill Workflow Truth Sync

**用户故事**：当维护者回看 `README.md` 的 Workflow Skill Boundary 图时，
不应该再看到 `list_candidates -> auto-review / confirm / reject` 这类旧主链，
因为当前 shipped distill review truth 已经是一等
`auto_review_candidates(project_name=<project>, apply=true)` surface。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | README workflow sync | README 的 distill workflow 图直接指向 `auto_review_candidates(apply=true)` |
| P1 | focused regression guard | README 回流到 `list_candidates -> auto-review / confirm / reject` 旧写法时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2920-readme-distill-workflow-truth-sync/`。
- `README.md` 的 Workflow Skill Boundary 图现在直接展示：
  - `prepare_session_distill`
  - `suggest_*`
  - `auto_review_candidates(apply=true)`
  - `final summary`
- 已补 focused regression test：`tests/test_readme_distill_truth.py`

## v2.9.21：V2 User Test Packet Distill Truth Sync

**用户故事**：当维护者回看 `docs/v2-user-test-packet.md` 的 generic MCP distill 流时，
不应该再看到 `suggest_* -> list_candidates -> auto_review_candidates` 这类旧主链，
因为当前 shipped distill review truth 已经是一等 `auto_review_candidates` surface。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | packet distill chain sync | v2 user test packet 的 generic MCP distill 链直接指向 `auto_review_candidates` |
| P1 | focused regression guard | packet 回流到 `list_candidates -> auto_review_candidates` 旧写法时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2921-user-test-packet-distill-truth-sync/`。
- `docs/v2-user-test-packet.md` 的 generic MCP distill 流现在直接展示：
  - `prepare_session_distill`
  - `suggest_*`
  - `auto_review_candidates`
- 已补 focused regression test：`tests/test_v2_user_test_packet_distill_truth.py`

## v2.9.22：Session-Distill Skill Truth Sync

**用户故事**：当维护者回看 `tools/session-distill/SKILL.md` 或 plugin README 的
`/hm:distill` 摘要时，不应该再看到 `list_candidates` 加逐条 confirm/reject 的旧主链，
因为当前 shipped distill review truth 已经是一等
`auto_review_candidates(project_name=<project>, apply=true)` surface。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | session-distill skill sync | skill 主链直接指向 `auto_review_candidates(project_name=<project>, apply=true)` |
| P0 | plugin distill summary sync | plugin README 的 `/hm:distill` 摘要明确提到 `auto_review_candidates` |
| P1 | focused regression guard | session-distill skill 回流到 `list_candidates -> confirm/reject` 主链时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2922-session-distill-skill-truth-sync/`。
- `tools/session-distill/SKILL.md` 现在明确：
  - default review surface 是 `auto_review_candidates(project_name=<project>, apply=true)`
  - `list_candidates` / `confirm_*` / `reject_*` 只保留给显式 drilldown 或 repair 流
- `plugins/harness-mem/README.md` 的 `/hm:distill` 摘要现在直接提到 `auto_review_candidates`
- 已补 focused regression test：`tests/test_session_distill_skill_truth.py`

## v2.9.23：AGENTS Distill Truth Sync

**用户故事**：当未来 agent 或维护者回看根 `AGENTS.md` 时，不应该再看到
`list_candidates` 加逐条 confirm/reject 的旧 distill 主链，因为当前 shipped review
truth 已经是一等 `auto_review_candidates(project_name=<project>, apply=true)` surface。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | AGENTS distill mainline sync | `AGENTS.md` 的 distill 主链直接指向 `auto_review_candidates(project_name=<project>, apply=true)` |
| P0 | repair boundary sync | `list_candidates` / `confirm_*` / `reject_*` 只保留给 repair 或 drilldown |
| P1 | focused regression guard | AGENTS 回流到旧 distill 主链时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2923-agents-distill-truth-sync/`。
- `AGENTS.md` 现在明确：
  - distill mainline 是 `prepare_session_distill -> suggest_* -> auto_review_candidates(project_name=<project>, apply=true)`
  - `list_candidates` / `confirm_*` / `reject_*` 只保留给 repair/recheck drilldown
- 已补 focused regression test：`tests/test_agents_distill_truth.py`

## v2.9.24：Roadmap-v22x Distill Truth Sync

**用户故事**：当维护者回看 `docs/roadmap-v22x.md` 这类历史版本线文档时，不应该再看到
`suggest_* -> list_candidates -> auto-review/confirm/reject` 这种旧 distill 主链，
因为当前 shipped review truth 已经是一等 `auto_review_candidates(apply=true)` surface。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap-v22x distill sync | v2.2 roadmap 的 distill 闭环表述直接指向 `auto_review_candidates(apply=true)` |
| P1 | focused regression guard | roadmap-v22x 回流到旧 distill 主链时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2924-roadmap-v22x-distill-truth-sync/`。
- `docs/roadmap-v22x.md` 现在把 distill 闭环写成：
  - `prepare_session_distill`
  - `session-distill`
  - `suggest_*`
  - `auto_review_candidates(apply=true)`
  - `summary`
- 已补 focused regression test：`tests/test_roadmap_v22x_distill_truth.py`

## v2.9.25：v2.9 Index Truth Sync

**用户故事**：当维护者只看 `docs/README.md` 或 `docs/roadmap-status.md` 这种高可见索引页时，
不应该再被“v2.9 只是 PRD sync candidate surface”误导，因为当前 shipped 的 `v2.9`
早已从 `/hm:prd-sync` 起步，扩展成一串 maintenance、triage 与 current-truth sync
release slices。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | docs index sync | `docs/README.md` 与 `docs/roadmap-status.md` 对 v2.9 的摘要对齐当前版本线真值 |
| P1 | focused regression guard | v2.9 索引回流到单一 `PRD sync candidate surface` 旧说法时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2925-v29-index-truth-sync/`。
- `docs/README.md` 现在把 `roadmap-v29.md` 描述为：
  - `v2.9 roadmap：PRD sync + maintenance/truth-sync release train`
- `docs/roadmap-status.md` 现在也把 `v2.9.x` 摘要写成：
  - 从 `/hm:prd-sync` 起步
  - 之后扩展为 maintenance / triage / truth-sync release train
- 已补 focused regression test：`tests/test_v29_index_truth.py`

## v2.9.26：Roadmap-Status Summary Truth Sync

**用户故事**：当维护者只看 `docs/roadmap-status.md` 底部短结论时，不应该再看到
“路线完成到 v2.8”的旧总结，因为当前 shipped 版本线已经连续发到 `v2.9.26`。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap-status short-summary sync | 底部“短结论”明确写出已连续收口到 `v2.9` |
| P1 | focused regression guard | 短结论回流到“完成到 v2.8”旧写法时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2926-roadmap-status-summary-truth-sync/`。
- `docs/roadmap-status.md` 的短结论现在明确：
  - 路线已连续收口到 `v2.9`
  - `v2.9` 包含 PRD sync / maintenance / triage / truth-sync release train
- 已补 focused regression test：`tests/test_roadmap_status_summary_truth.py`

## v2.9.28：Roadmap-Status Baseline Truth Sync

**用户故事**：当维护者只看 `docs/roadmap-status.md` 顶部“当前收口基线”摘要时，
不应该再看到一段只枚举到 `v2.9.11` 的旧摘要，因为当前 shipped 版本线已经连续发到
`v2.9.27`。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap-status baseline sync | 顶部“当前收口基线”摘要明确把 `v2.9.0–v2.9.27` 视作已完成 release train |
| P1 | focused regression guard | 顶部摘要回流到只写到 `v2.9.11` 的旧口径时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2928-roadmap-status-baseline-truth-sync/`。
- `docs/roadmap-status.md` 的顶部“当前收口基线”摘要现在明确：
  - `v2.9.0–v2.9.27` 是一整条已完成的 release train
  - 不再把这段高可见摘要停在 `v2.9.11`
- 已补 focused regression test：`tests/test_roadmap_status_baseline_truth.py`

## v2.9.29：Roadmap-Status Matrix Truth Sync

**用户故事**：当维护者查看 `docs/roadmap-status.md` 的完成矩阵时，不应该再看到历史版本
行仍被标成“当前收口基线”，因为这些状态只在当时发版瞬间成立，对当前 repo 真值已经过期。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap-status matrix sync | 历史版本行不再保留“当前收口基线”状态；当前版本单独保留 `当前版本` |
| P1 | focused regression guard | 矩阵回流到历史版本仍显示“当前收口基线”时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2929-roadmap-status-matrix-truth-sync/`。
- `docs/roadmap-status.md` 的完成矩阵现在明确：
  - `v2.8.2`、`v2.9.8` 等历史行回写为 `已完成`
  - 只有当前版本行保留 `当前版本`
- 已补 focused regression test：`tests/test_roadmap_status_matrix_truth.py`

## v2.9.30：Roadmap-v25 Status Truth Sync

**用户故事**：当维护者回看 `docs/roadmap-v25.md` 头部状态和 `v2.5.2` 小节时，
不应该再看到“进行中”或“待发版”的旧口径，因为 `Context Assembly + File Context`
早已并入正式版本线。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap-v25 header sync | `roadmap-v25` 头部状态明确写成 `v2.5.0 / v2.5.1 / v2.5.2 已完成` |
| P0 | file-context section sync | `v2.5.2` 小节不再保留“待发版”说法 |
| P1 | focused regression guard | `roadmap-v25` 回流到“进行中 / 待发版”旧口径时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2930-roadmap-v25-status-truth-sync/`。
- `docs/roadmap-v25.md` 现在明确：
  - `v2.5.0 / v2.5.1 / v2.5.2` 已完成
  - `v2.5.2` 已并入正式版本线，不再写成“待发版”
- 已补 focused regression test：`tests/test_roadmap_v25_status_truth.py`

## v2.9.31：Roadmap-v22x Status Truth Sync

**用户故事**：当维护者回看 `docs/roadmap-v22x.md` 头部状态时，不应该再看到“规划中”，
因为 `v2.2` 早已作为已完成版本线并入当前真值。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap-v22x header sync | `roadmap-v22x` 头部状态明确写成已完成，而不是规划中 |
| P1 | focused regression guard | `roadmap-v22x` 回流到“规划中”旧口径时测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2931-roadmap-v22x-status-truth-sync/`。
- `docs/roadmap-v22x.md` 现在明确：
  - `v2.2.0` 已完成
  - 不再把该版本线写成“规划中”
- 已补 focused regression test：`tests/test_roadmap_v22x_status_truth.py`

## v2.9.32：Historical Draft Status Truth Sync

**用户故事**：当维护者打开 `docs/roadmap/dream-mechanism-absorption-v151-v17.md`
这类历史设计稿时，不应该只看到一个裸 `draft` 状态，因为相关版本线早已完成，
真正需要传达的是“这是历史草稿，不是当前 roadmap 承诺”。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | historical draft header sync | 该历史设计稿头部状态明确写成“历史设计稿（draft archive）”，并指向当前真值来源 |
| P0 | docs index sync | `docs/README.md` 把 `docs/roadmap/` 描述为历史 proposal / design drafts，而不是当前版本规划 |
| P1 | focused regression guard | 如果该文档回流到裸 `> 状态：draft`，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2932-historical-draft-status-truth-sync/`。
- `docs/roadmap/dream-mechanism-absorption-v151-v17.md` 现在明确：
  - 这是历史设计稿（draft archive）
  - 不是当前版本路线图
  - 当前版本状态应以 `docs/roadmap-status.md` 与 `CHANGELOG.md` 为准
- `docs/README.md` 现在也把 `docs/roadmap/` 标成历史 proposal / design drafts。
- 已补 focused regression test：`tests/test_historical_draft_status_truth.py`

## v2.9.33：Vision Authority Truth Sync

**用户故事**：当维护者打开 `docs/roadmap-vision-v16-v18.md` 和
`docs/reference-projects.md` 时，不应该再把这类历史 vision 文档误读成当前版本承诺依据。
相关 `v1.6` - `v1.8` 早已完成，当前真值来源应该明确回到 `roadmap-status` 与 `CHANGELOG`。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | vision header sync | `roadmap-vision-v16-v18.md` 头部明确写成历史远景文档，并指向当前真值来源 |
| P0 | reference authority sync | `reference-projects.md` 不再把 `roadmap-vision-v16-v18.md` 写成当前路线承诺依据 |
| P1 | docs index sync | `docs/README.md` 把 `roadmap-vision-v16-v18.md` 描述成历史远景方向 |
| P1 | focused regression guard | 如果 vision 文档回流到旧 authority 口径，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2933-vision-authority-truth-sync/`。
- `docs/roadmap-vision-v16-v18.md` 现在明确：
  - 这是历史远景文档（vision archive）
  - 不是当前版本承诺路线图
  - 当前版本状态应以 `roadmap-status.md` 与 `CHANGELOG.md` 为准
- `docs/reference-projects.md` 现在也回写为：
  - 当前版本状态以 `roadmap-status.md` 与 `CHANGELOG.md` 为准
  - `roadmap-v15x` / `v16x` / `v17x` / `vision` 只作为历史路线设计参考
- 已补 focused regression test：`tests/test_vision_authority_truth.py`

## v2.9.34：Roadmap-Status v2.9 Baseline Tail Sync

**用户故事**：当维护者只看 `docs/roadmap-status.md` 顶部“当前收口基线”摘要时，
不应该再看到 `v2.9` release train 被截在 `v2.9.27`，因为后续 `v2.9.28` 到当前版本
也已经是同一条连续收口线。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap-status tail sync | 顶部摘要把 `v2.9` release train 尾号同步到当前版本 |
| P1 | focused regression guard | baseline test 改为跟随 `__version__` 校验，不再写死旧尾号 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2934-roadmap-status-v29-baseline-tail-sync/`。
- `docs/roadmap-status.md` 的顶部“当前收口基线”摘要现在明确：
  - `v2.9.0–v2.9.34` 是当前完整的 v2.9 release train
  - 不再把该摘要停在 `v2.9.27`
- `tests/test_roadmap_status_baseline_truth.py` 现在会跟随 `harness_mem.__version__` 校验。

## v2.9.35：Docs README Status Range Truth Sync

**用户故事**：当维护者查看 `docs/README.md` 里的文档索引时，不应该把
`roadmap-status.md` 误读成只覆盖 `v1.6` 之后的版本，因为当前完成矩阵已经明确包含
`v1.5.x` 这一历史基础线。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | docs README status-range sync | `docs/README.md` 把 `roadmap-status.md` 描述成覆盖 `v1.5` 到 `v2.9` |
| P1 | focused regression guard | 如果 README 回流到 `v1.6` 起算的旧口径，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2935-docs-readme-status-range-truth-sync/`。
- `docs/README.md` 现在明确：
  - `roadmap-status.md` 覆盖 `v1.5` 到 `v2.9`
  - 不再把覆盖范围缩成 `v1.6` 起步
- 已补 focused regression test：`tests/test_docs_readme_status_range_truth.py`

## v2.9.36：Roadmap-Status Short Summary Scope Sync

**用户故事**：当维护者只看 `docs/roadmap-status.md` 的“短结论”时，不应该误以为
当前已完成主线是从 `v2.2` 才开始，因为该状态页和完成矩阵已经明确覆盖 `v1.5` 到 `v2.9`
的连续历史范围。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap-status short summary sync | “短结论”明确从 `v1.5` 到 `v2.9` 总结已完成主线，而不是只从 `v2.2` 起讲 |
| P1 | focused regression guard | summary 测试拒绝回流到只从 `v2.2` 起讲的旧口径 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2936-roadmap-status-short-summary-scope-sync/`。
- `docs/roadmap-status.md` 的“短结论”现在明确：
  - 从 `v1.5` baseline 到 `v2.9` release train 都属于连续已完成主线
  - 不再只从 `v2.2` 用户入口闭环开始概括
- 已补 focused regression test：`tests/test_roadmap_status_summary_truth.py`

## v2.9.37：Roadmap-Status Version Index Truth Sync

**用户故事**：当维护者查看 `docs/roadmap-status.md` 的版本索引表时，不应该再只看到
`v2.2.x` 之后的条目，因为当前状态页和短结论都已经明确覆盖 `v1.5` 到 `v2.9` 的连续历史范围。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap-status version-index sync | 高可见版本索引表从 `v1.5.x` 连续覆盖到 `v2.9.x` |
| P0 | section label sync | 节名不再写“后续 Roadmap”，而是写成当前真值导向的“版本索引” |
| P1 | focused regression guard | 如果索引表回流到只从 `v2.2.x` 起列，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2937-roadmap-status-version-index-truth-sync/`。
- `docs/roadmap-status.md` 的高可见版本索引现在明确：
  - 从 `v1.5.x` 到 `v2.9.x` 连续列出对应 roadmap / status 文档
  - 不再以“后续 Roadmap”名义只从 `v2.2.x` 开始
- 已补 focused regression test：`tests/test_roadmap_status_version_index_truth.py`

## v2.9.38：Roadmap-Status Baseline Scope Sync

**用户故事**：当维护者只看 `docs/roadmap-status.md` 顶部 baseline 摘要时，不应该误以为
当前已完成主线是从 `v2.5` 才开始，因为同页的短结论和版本索引已经明确覆盖 `v1.5` 到 `v2.9`
的连续历史范围。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap-status baseline scope sync | 顶部 baseline 摘要明确从 `v1.5` 到 `v2.9` 总结已完成主线 |
| P1 | focused regression guard | baseline 测试拒绝回流到只从 `v2.5` 起讲的旧口径 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2938-roadmap-status-baseline-scope-sync/`。
- `docs/roadmap-status.md` 的顶部 baseline 摘要现在明确：
  - 从 `v1.5` baseline 到 `v2.9` release train 都属于连续已完成主线
  - 不再只从 `v2.5` context-assembly 线开始概括
- 已补 focused regression test：`tests/test_roadmap_status_baseline_truth.py`

## v2.9.39：Opt-In Hook Truth Sync

**用户故事**：当维护者查看根 README 或 AGENTS 时，不应该再被“当前产品没有 IDE hook”这种绝对句误导，因为 v2.4 已经交付了默认 `off` 的 opt-in host hook / scheduler trigger。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | README/AGENTS hook truth sync | 两份高可见文档都明确写成“没有默认自动随手记；已有 opt-in hook，默认 off” |
| P1 | focused regression guard | 如果 README 或 AGENTS 回流到“没有 IDE hook”的绝对句，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2939-opt-in-hook-truth-sync/`。
- `README.md` 与 `AGENTS.md` 现在明确：
  - 没有默认后台 daemon / 默认自动随手记
  - 已存在 opt-in host hook / scheduler trigger
  - `triggers.*` 默认仍是 `off`
- 已补 focused regression test：`tests/test_opt_in_hook_truth.py`

## v2.9.40：Best-Practices Wake Drilldown Truth Sync

**用户故事**：当维护者查看 `docs/best-practices.md` 的 runtime 工具表时，不应该把
`get_task_handoffs` / `get_confirmed_rules` 误解成默认 wake-up 起点，因为当前 shipped
truth 已经明确：新 session 先走一等 MCP `wake`，低层读工具只在显式 drilldown 时再用。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | best-practices wake drilldown sync | `wake` 行明确覆盖新 session 常见的 profile/rules/handoff 读取需求；`get_task_handoffs` / `get_confirmed_rules` 只描述为显式 drilldown |
| P1 | focused regression guard | 如果 `best-practices` 回流到把这两个低层读工具摆成默认 wake-up 起点，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2940-best-practices-wake-drilldown-truth-sync/`。
- `docs/best-practices.md` 现在明确：
  - `wake` 是默认 read surface，并覆盖新 session 常见的 profile/rules/handoff 读取
  - `get_task_handoffs` / `get_confirmed_rules` 只在显式 drilldown provenance 或原始细节时再读取
  - 不再把这些低层读工具摆成默认 wake-up 主路径
- 已补 focused regression test：`tests/test_best_practices_wake_drilldown_truth.py`

## v2.9.42：Roadmap-v29 Status Range Truth Sync

**用户故事**：当维护者只看 `docs/roadmap-v29.md` 的顶部状态行时，不应该误以为
`v2.9` release train 只完成到某个手工枚举的 patch，因为这条头部摘要在 `v2.9`
阶段已经频繁发生尾号滞后。当前文档应该直接和版本真值保持范围式对齐，而不是继续列出
越来越长、且每发一版就立刻过时的 patch 清单。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap-v29 status range sync | 顶部状态行改成 `v2.9.0–v2.9.43 已完成` 这类范围式摘要，并和当前版本真值对齐 |
| P1 | focused regression guard | 如果顶部状态行回流到旧的逐 patch 枚举尾号写法，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2942-roadmap-v29-status-range-truth-sync/`。
- `docs/roadmap-v29.md` 顶部状态行现在明确：
  - 用 `v2.9.0–v2.9.43 已完成` 这类范围式摘要对齐当前版本真值
  - 不再继续维护逐 patch 枚举、且易于立刻过时的头部状态行
- 已补 focused regression test：`tests/test_roadmap_v29_status_tail_truth.py`

## v2.9.43：User-Test-Packet Contract Source Truth Sync

**用户故事**：当维护者查看 `docs/v2-user-test-packet.md` 时，不应该再被指向一个已归档
的 `openspec/changes/v220...` 路径，也不应该依赖“Codex CLI 当前版本所支持的写法”
这种外部客户端时态。当前 packet 应直接回指主 `daily-workflow` spec，并只描述 repo 自己
维护和验证的 MCP stdio 契约。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | user-test-packet contract-source sync | packet 的契约真值源改成 `openspec/specs/daily-workflow/spec.md` |
| P0 | Codex MCP wording sync | Codex 接入说明改成 repo 当前维护并验证的 stdio 契约，不再写“当前版本客户端支持写法” |
| P1 | focused regression guard | 如果 packet 再回流到 archived change 路径或外部客户端时态，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2943-user-test-packet-contract-source-truth-sync/`。
- `docs/v2-user-test-packet.md` 现在明确：
  - 契约真值源是 `openspec/specs/daily-workflow/spec.md`
  - Codex MCP 接入说明只描述 repo 当前维护并验证的 stdio 契约
  - 不再依赖 archived change 路径或“当前版本客户端支持写法”这种外部漂移口径
- 已补 focused regression test：`tests/test_v2_user_test_packet_contract_source_truth.py`

## v2.9.44：Roadmap-v29 Archive Pointer Truth Sync

**用户故事**：当维护者回读 `docs/roadmap-v29.md` 的前半段已完成切片时，不应该再看到
`openspec/changes/v29xx...` 这种像 active change 一样的路径，因为这些变更早就归档了。
当前 roadmap 应直接回指 archive 真路径，而不是保留过时的 change 目录口径。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | completed-slice pointer sync | `v290`–`v2912` 已完成条目统一回指 archive 路径 |
| P1 | focused regression guard | 如果 `roadmap-v29` 再回流到这些早期 v29 切片的 active-change 路径，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2944-roadmap-v29-archive-pointer-truth-sync/`。
- `docs/roadmap-v29.md` 现在明确：
  - `v290`–`v2912` 的已完成条目统一回指 archive 真路径
  - 不再把这些已归档切片写成仍在 `openspec/changes/v29xx...` 的 active-change 口径
- 已补 focused regression test：`tests/test_roadmap_v29_archive_pointer_truth.py`

## v2.9.45：Roadmap-v27-v28 Archive Pointer Truth Sync

**用户故事**：当维护者回读 `docs/roadmap-v27.md` 和 `docs/roadmap-v28.md` 时，不应该再看到
已完成切片仍指向 `openspec/changes/v27x...` / `v28x...` 这种 active change 路径，因为这些
变更都已经归档。当前 roadmap 应直接回指 archive 真路径。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | roadmap-v27 archive-pointer sync | `v270`–`v272` 已完成条目统一回指 archive 路径 |
| P0 | roadmap-v28 archive-pointer sync | `v280`–`v282` 已完成条目统一回指 archive 路径 |
| P1 | focused regression guard | 如果这两份 roadmap 再回流到早期已归档切片的 active-change 路径，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2945-roadmap-v27-v28-archive-pointer-truth-sync/`。
- `docs/roadmap-v27.md` 与 `docs/roadmap-v28.md` 现在明确：
  - `v270`–`v272` 和 `v280`–`v282` 的已完成条目统一回指 archive 真路径
  - 不再把这些已归档切片写成仍在 `openspec/changes/v27x...` / `v28x...` 的 active-change 口径
- 已补 focused regression test：`tests/test_roadmap_v27_v28_archive_pointer_truth.py`

## v2.9.46：Historical Roadmap And Skill Archive Pointer Truth Sync

**用户故事**：维护者回读历史版本 roadmap 和 repo-local skill 时，不应该再看到已归档切片仍写成
`openspec/changes/v16x...` / `v17x...` / `v23x...` 这种 active-change 路径，也不应该把
当前主 spec 写成不存在的 `memory-metabolism` 目录。历史资料可以保留，但指针必须回到 archive
真路径和当前主 spec 真值。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | historical roadmap archive-pointer sync | `roadmap-v16x`、`roadmap-v17x`、`roadmap-v23` 的已完成切片回指 archive 真路径 |
| P0 | session-distill metabolism spec sync | `tools/session-distill/SKILL.md` 改为 archive design + 当前 `openspec/specs/metabolism/spec.md` |
| P1 | focused regression guard | 如果这些高可见历史文档和 skill 再回流到 stale active-change 路径或错误 main-spec 路径，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2946-historical-roadmap-and-skill-archive-pointer-truth-sync/`。
- 历史 roadmap / skill 现在明确：
  - `roadmap-v16x`、`roadmap-v17x`、`roadmap-v23` 的已完成切片回指 archive 真路径
  - `session-distill/SKILL.md` 回指已归档的 `v230` design 和当前主 `metabolism` spec
  - 不再把这些已归档切片写成仍在 active change 目录里，也不再引用不存在的 `memory-metabolism` spec 路径
- 已补 focused regression test：`tests/test_historical_archive_pointer_truth.py`

## v2.9.47：Docs README OpenSpec Layout Truth Sync

**用户故事**：维护者阅读 [docs/README.md](./README.md) 时，不应该再把 `openspec/specs/`、
`openspec/changes/` 和归档 change 混成一个模糊面。当前 repo 已没有 active change，因此索引页
应该直接把主 spec、active changes、archive 三层职责讲清楚，而不是继续写成“设计规格在
`openspec/specs/` 和 `openspec/changes/`”。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | docs README OpenSpec layout sync | `docs/README.md` 明确区分主 spec、active changes、archive |
| P1 | focused regression guard | 如果 `docs/README.md` 再回流到旧的两目录混写口径，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2947-docs-readme-openspec-layout-truth-sync/`。
- `docs/README.md` 现在明确：
  - `openspec/specs/` 是当前主 spec 真值
  - `openspec/changes/` 是仍在进行中的 active changes
  - `openspec/changes/archive/` 是已完成 change 的归档记录
- 已补 focused regression test：`tests/test_docs_readme_openspec_layout_truth.py`

## v2.9.48：User-Test-Packet OpenSpec Source Hierarchy Sync

**用户故事**：维护者照着 [v2-user-test-packet.md](./v2-user-test-packet.md) 修客户端口径时，
不应该把 `openspec/changes/<change>/specs/...` 误当成默认 spec 真值入口。当前 repo 已没有
active change，因此测试包应明确：默认先看主 `openspec/specs/...`，只有真的在审 active change
proposal 时才下钻到 `openspec/changes/<change>/specs/...`。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | user-test-packet OpenSpec source hierarchy sync | `v2-user-test-packet.md` 明确主 spec 默认、active change proposal 仅作条件性下钻 |
| P1 | focused regression guard | 如果测试包再回流到把 `openspec/changes/<change>/specs/...` 写成普通默认路径，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2948-user-test-packet-openspec-source-hierarchy-sync/`。
- `docs/v2-user-test-packet.md` 现在明确：
  - 默认看 `openspec/specs/...` 作为当前主 spec 真值
  - 只有确实存在 active change proposal 时，才下钻 `openspec/changes/<change>/specs/...`
- 已补 focused regression test：`tests/test_v2_user_test_packet_contract_source_truth.py`

## v2.9.49：Root README And AGENTS OpenSpec Layout Truth Sync

**用户故事**：维护者回读 repo 根 [README.md](../README.md) 和 [AGENTS.md](../AGENTS.md) 时，
不应该只看到一个笼统的 `openspec/` 目录说明。当前 repo 已没有 active change，高可见根说明面
也应该和 `docs/README.md` 对齐，明确区分主 spec、active changes 和 archive。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | root OpenSpec layout sync | README / AGENTS 明确区分 `openspec/specs/`、`openspec/changes/`、`openspec/changes/archive/` |
| P1 | focused regression guard | 如果根说明面再回流到笼统 `openspec/` 桶描述，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2949-root-readme-and-agents-openspec-layout-truth-sync/`。
- repo 根说明面现在明确：
  - `openspec/specs/` 是当前主 spec 真值
  - `openspec/changes/` 是仍在进行中的 active changes
  - `openspec/changes/archive/` 是已完成 change 的归档记录
- 已补 focused regression test：`tests/test_repo_openspec_layout_truth.py`

## v2.9.50：Root Truth Authority Sync

**用户故事**：维护者从 repo 根入口开始看项目时，不应该只知道 `AGENTS.md` 讲协作、roadmap 讲设计，
却不知道“当前到底 shipped 了什么、边界在哪里”该看哪个 authority。根 README 和 AGENTS 都应该
直接指向 `docs/roadmap-status.md` 与 `CHANGELOG.md`，避免把历史 roadmap 当成当前实现真值。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | root truth-authority sync | README / AGENTS 明确把当前发版状态和边界 authority 指向 `roadmap-status.md` + `CHANGELOG.md` |
| P1 | focused regression guard | 如果根入口再缺失这两个 authority 指针，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2950-root-truth-authority-sync/`。
- repo 根入口现在明确：
  - `AGENTS.md` 负责协作与事实面
  - 当前发版状态、已完成切片和未做边界看 `docs/roadmap-status.md` 与 `CHANGELOG.md`
  - 各版本 roadmap 主要保留切片设计与历史决策链，不单独充当当前实现真值
- 已补 focused regression test：`tests/test_root_truth_authority_sync.py`

## v2.9.51：Docs README Truth Authority Sync

**用户故事**：维护者从 [docs/README.md](./README.md) 进入文档索引时，不应该只看到文件列表，
却还得自己猜“当前发版真值看哪里”。docs 索引页也应该和根入口一致，直接把当前 shipped 状态、
已完成切片和未做边界 authority 指向 `roadmap-status.md` 与 `CHANGELOG.md`。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | docs README truth-authority sync | `docs/README.md` 明确把当前发版状态与边界 authority 指向 `roadmap-status.md` + `CHANGELOG.md` |
| P1 | focused regression guard | 如果 docs 索引页再缺失这两个 authority 指针，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2951-docs-readme-truth-authority-sync/`。
- docs 文档入口现在明确：
  - 当前发版状态、已完成切片和未做边界看 `roadmap-status.md` 与 `CHANGELOG.md`
  - 各版本 roadmap 主要保留切片设计、验收口径和历史决策链，不单独充当当前实现真值
- 已补 focused regression test：`tests/test_docs_readme_truth_authority_sync.py`

## v2.9.52：Usage Docs Truth Authority Sync

**用户故事**：维护者或使用者从 plugin README 和 best-practices 这类高可见使用文档进入时，
不应该只看到安装和操作建议，却不知道当前 shipped 状态和边界要看哪里。使用文档也应明确把
authority 指向 `roadmap-status.md` 与 `CHANGELOG.md`。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | usage-doc authority sync | `plugins/harness-mem/README.md` 与 `docs/best-practices.md` 明确把当前发版状态与边界指向 `roadmap-status.md` + `CHANGELOG.md` |
| P1 | focused regression guard | 如果这些高可见使用文档再缺失 authority 指针，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2952-usage-docs-truth-authority-sync/`。
- 高可见使用文档现在明确：
  - plugin README 与 best-practices 的当前发版状态、已完成切片和未做边界都看 `roadmap-status.md` 与 `CHANGELOG.md`
  - 它们聚焦安装、集成和使用建议，不单独充当当前实现真值
- 已补 focused regression test：`tests/test_usage_docs_truth_authority_sync.py`

## v2.9.53：Reference Docs Truth Authority Sync

**用户故事**：维护者从 `docs/cli/v2.4.md`、`docs/error-codes.md` 或
`docs/cli-design-expert.md` 这些高可见参考文档进入时，不应该把操作说明、错误码表或设计准则误当成
当前发版真值来源。参考文档也应明确把 shipped 状态与边界 authority 指向 `roadmap-status.md`
与 `CHANGELOG.md`。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | reference-doc authority sync | CLI operator doc、error-codes、cli-design-expert 明确把当前发版状态与边界指向 `roadmap-status.md` + `CHANGELOG.md` |
| P1 | focused regression guard | 如果这些高可见参考文档再缺失 authority 指针，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2953-reference-docs-truth-authority-sync/`。
- 高可见参考文档现在明确：
  - `docs/cli/v2.4.md`、`docs/error-codes.md`、`docs/cli-design-expert.md` 的当前发版状态与边界都看 `roadmap-status.md` 与 `CHANGELOG.md`
  - 这些文档聚焦 operator reference、错误码和设计原则，不单独充当当前实现真值
- 已补 focused regression test：`tests/test_reference_docs_truth_authority_sync.py`

## v2.9.54：v2.2 Manual Gate Truth Sync

**用户故事**：当维护者回看 `docs/roadmap-v22x.md`、`docs/roadmap-status.md` 和
`docs/v2-user-test-packet.md` 时，不应该同时看到 “v2.2 已完成” 和 “非 Claude client
未跑” 这两种互相冲突的说法。这个切片当时的真值是：runtime / contract 已落地，但手工
cross-client release gate 仍缺非 Claude client 的 Run log entry；该缺口后来已被
`2026-06-03` 的 non-Claude entries 补齐。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | v2.2 status truth sync | `roadmap-v22x` 与 `roadmap-status` 明确区分 runtime completion 和未闭的 manual cross-client gate |
| P1 | focused regression guard | 如果 packet 仍写 non-Claude 未跑，而 roadmap 却重新写成“v2.2 已完成”，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2954-v22-manual-gate-truth-sync/`。
- `v2.2` 的完成性表述现在已收回到当前真值：
  - runtime / contract 已落地
  - loop harness 已提供 automated non-Claude parity evidence
  - 当时 `docs/v2-user-test-packet.md` 的 Run log 仍缺 release gate 要求的非 Claude client entry
- 已补 focused regression test：`tests/test_v22_manual_gate_truth.py`

## v2.9.55：v2.2 Non-Claude Smoke Log Sync

**用户故事**：当维护者回看 `docs/v2-user-test-packet.md` 时，不应该再看到 “非 Claude
client 完全未跑” 这种已经被当前机器上的 Codex MCP smoke 证据推翻的说法；但也不能把
一次最小 smoke 误写成 full cross-client matrix 已闭环。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | packet run-log truth sync | `v2-user-test-packet` 增加 1 条可核验的 Codex non-Claude smoke entry |
| P0 | status wording sync | `roadmap-v22x` / `roadmap-status` 改成“已有 non-Claude smoke，但 full matrix 未闭” |
| P1 | focused regression guard | 如果 packet 已有 non-Claude smoke entry，却仍写成“非 Claude client 未跑”，测试失败 |

### 当前状态（2026-06-03）

- 已完成 `openspec/changes/archive/2026-06-03-v2955-v22-non-claude-smoke-log-sync/`。
- `v2-user-test-packet` 现在新增 1 条 Codex MCP smoke entry，覆盖：
  - empty-project `wake`
  - `set_active_project`
  - `suggest_memory_entry`
- `v2.2` 的手工 gate 口径也同步到更精确的当前真值：
  - 已有 1 条 non-Claude smoke
  - 但 full 12-scenario matrix 与 Cursor / generic MCP run log 仍未补齐
- 后续 `2026-06-03` 的额外 Run log 已把 OpenSpec `5.5` 手工 gate 彻底补齐；该节保留的是
  当时 `v2.9.55` 发版瞬间的状态。
- 已补 focused regression test：`tests/test_v22_manual_gate_truth.py`

## v2.9.56：Fresh-Home Write-Path Embedding Fail-Fast

**用户故事**：当维护者在 fresh isolated home 下用 generic MCP 或其它交互式 client
直接跑 `suggest_memory_entry` 时，不应该因为 write-path embedding 触发首次 Hugging Face
模型下载而把整条写入路径拖到超时。cold cache 下，候选写入应先成功返回；vec row 可以留给后续
重建或缓存就绪后再补。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | cold-cache write-path skip | 没有本地 model snapshot 时，`persist_embedding` 直接跳过 vec 写入，不触发 cold download |
| P0 | live fresh-home packet evidence | `docs/v2-user-test-packet.md` 追加 real stdio MCP run，证明 embeddings enabled 的 fresh-home 写路径快速返回 |
| P1 | focused regression guard | cold-cache 条件下 write path 不得再尝试 `get_model_loader(...)` |

### 当前状态（2026-06-04）

- 已完成 `openspec/changes/archive/2026-06-04-v2956-fresh-home-write-path-embedding-failfast/`。
- write-path embedding 现在明确分成两类 best-effort fail-fast：
  - **cold cache**：本地没有 cached model snapshot 时，直接跳过 vec 写入并记 warning
  - **cached-but-hung encode/import**：沿用已有 timeout / circuit-breaker
- `docs/v2-user-test-packet.md` 现在已追加一条 `2026-06-04` generic MCP fresh-home
  smoke：在 isolated temp home、不开 `HARNESS_MEM_DISABLE_EMBEDDINGS` 的条件下，
  `suggest_memory_entry` 已在当前机器上快速返回，并且 `list_candidates` 能读回同一条 pending entry。
- 已补 focused regression coverage：`tests/test_disable_embeddings.py`

## v2.9.57：Generic MCP Empty-Packet S6 Evidence

**用户故事**：当维护者回看 `docs/v2-user-test-packet.md` 的 generic MCP coverage 时，
不应该只看到最小 read/write smoke、S8/S9 deeper workflow 和 fresh-home write-path fix，
却仍缺一条真正对应 packet `S6 Empty evidence packet` 的实跑证据。至少要有一条 live stdio
`prepare_session_distill` 空包 entry，证明 empty-project 场景已经在当前机器上跑过。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | generic MCP S6 evidence | `v2-user-test-packet` 追加一条 live stdio `prepare_session_distill(run_ingest=false)` 空包 entry |
| P1 | focused regression guard | 如果这条 empty-packet evidence 再次消失，测试失败 |

### 当前状态（2026-06-04）

- 已完成 `openspec/changes/archive/2026-06-04-v2957-generic-mcp-empty-packet-s6-evidence/`。
- `docs/v2-user-test-packet.md` 现在新增一条 `2026-06-04` generic MCP empty-packet entry，记录：
  - isolated temp home
  - `prepare_session_distill(run_ingest=false)`
  - `observation_count = 0`
  - 零 status counters
  - `observations = []`
- 已补 focused regression coverage：`tests/test_v2_user_test_packet_empty_evidence_truth.py`

## v2.9.58：Generic MCP Cross-Session S10 Evidence

**用户故事**：当维护者回看 packet 的 generic MCP coverage 时，不应该只看到单会话 smoke、
S6 empty packet、S8/S9 workflow 和 fresh-home write-path，而还缺一条“确认过的 truth
能不能被下一次会话读回”的 live evidence。至少要有两个独立 MCP 会话之间的 confirmed-truth
visibility 记录，证明 writer 会话确认的事实，reader 会话的 `wake` 已能读回。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | generic MCP cross-session S10 evidence | `v2-user-test-packet` 追加 writer/reader 两个独立 stdio MCP 会话间的 confirmed-truth visibility entry |
| P1 | focused regression guard | 如果这条 cross-session truth evidence 再次消失，测试失败 |

### 当前状态（2026-06-04）

- 已完成 `openspec/changes/archive/2026-06-04-v2958-generic-mcp-cross-session-s10-evidence/`。
- `docs/v2-user-test-packet.md` 现在新增一条 `2026-06-04` generic MCP cross-session entry，记录：
  - writer 会话 `suggest_memory_entry` -> `confirm_memory_entry`
  - reader 会话 `wake(no_auto_ingest=true)`
  - confirmed truth 出现在 `# Essential Truth (L1 · confirmed current)`
- 已补 focused regression coverage：`tests/test_v2_user_test_packet_cross_session_truth.py`

## v2.9.59：Generic MCP S12 Repair-Only Distill Summary

**用户故事**：当维护者回看 packet 的 generic MCP distill coverage 时，不应该再把 `/hm:review`
误读成 distill 成功后的默认下一步。至少要有一条 live summary evidence，证明成功的
`auto_review_candidates(apply=true)` 结果不会把用户默认推去 `/hm:review`，而只会把 deferred
candidates 作为 repair / follow-up 说明出来。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | generic MCP S12 evidence | `v2-user-test-packet` 追加一条成功 auto-review summary 不含 `/hm:review` 的 live entry |
| P1 | focused regression guard | 如果这条 repair-only evidence 再次消失，测试失败 |

### 当前状态（2026-06-04）

- 已完成 `openspec/changes/archive/2026-06-04-v2959-generic-mcp-s12-repair-only-summary/`。
- `docs/v2-user-test-packet.md` 现在新增一条 `2026-06-04` generic MCP summary entry，记录：
  - `auto_review_candidates(..., apply=true)` 成功返回
  - payload 不含 `/hm:review`
  - `next_user_action` 直接写成 review deferred candidates
- 已补 focused regression coverage：`tests/test_v2_user_test_packet_review_only_truth.py`

## v2.9.60：Packet S11 Stale CLI Surface Evidence

**用户故事**：当维护者回看 packet 的 `S11 Stale CLI surface absence` 时，不应该只看到一条
“去 grep” 的测试说明，而应该有一条当前仓库真值的结果记录：在 packet 指定的文档范围里，
`harness-mem wake/search/timeline/candidates/distill` 这些旧 daily CLI 面是否还在被当成用户 path 教。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | packet S11 evidence | `v2-user-test-packet` 追加 packet-defined grep 的当前结果 |
| P1 | focused regression guard | 如果这条 stale-CLI evidence 再次消失，测试失败 |

### 当前状态（2026-06-04）

- 已完成 `openspec/changes/archive/2026-06-04-v2960-packet-s11-stale-cli-surface-evidence/`。
- `docs/v2-user-test-packet.md` 现在新增一条 `2026-06-04` stale-CLI scan entry，记录：
  - packet 规定的扫描命令
  - 当前命中只剩“已删除/不要求手动跑”的反例说明
  - packet 范围内没有把旧 daily CLI 面当成当前用户 path 教学的命中
- 已补 focused regression coverage：`tests/test_v2_user_test_packet_stale_cli_truth.py`

## v2.9.61：Packet Remaining-Evidence Guardrails + Stronger S4/S10 Near-Neighbors

**用户故事**：当维护者继续补 `v2-user-test-packet` 时，不应该把 generic MCP 的底层 runtime repro、
wake renderer 读端 readback，或者 Cursor runtime/cache/transcript 旁证误写成 full matrix 已完成。
仓库需要同时做到两件事：一是把当前仍缺的强证据类别固定成可回归校验的 repo 真值；二是把
`S4` 和 `S10` 往更强的 repo-owned near-neighbor evidence 再推进一步。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | remaining-evidence guardrails | 防止 packet/roadmap 再把旁证抬成 UI 级 cross-client 完成 |
| P0 | S4 lower-layer repro | 固定当前机器上真实可复现的一种 MCP transport-unavailable 根因 |
| P0 | S10 wake-renderer read-side evidence | 把 confirmed-truth readback 从 raw MCP payload 推进到真实 `cmd_wake_up` 读端 |
| P1 | focused regression coverage | 让上述 truth 不再只靠手工回读 |

### 当前状态（2026-06-04）

- 当前已补的 stronger near-neighbor evidence：
  - `S4` generic MCP 底层 transport-unavailable repro：
    - 故意把启动目标改成 `python -m harness_mem.mcp.server_missing`
    - 子进程在 JSON-RPC 握手前直接失败
    - `stderr` 返回 `No module named harness_mem.mcp.server_missing`
  - `S10` wake-renderer read-side evidence：
    - temp backend 存一条 accepted current-truth entry
    - `cmd_wake_up(..., no_auto_ingest=true)` 成功
    - rendered output 在 `# Essential Truth  (L1 · confirmed current)` 下读回该事实
  - Hermes oneshot runtime evidence：
    - `hermes -z "reply with the single word ok" --yolo` 正常返回 `ok`
    - Hermes 已能在本仓库里写入并确认 `Hermes cross-client sentinel fact.`
    - 随后被真实 `cmd_wake_up("harness-mem", no_auto_ingest=true)` 读回
  - direct UI-level `S10` pair transcript：
    - write-side = `Codex app`
    - read-side = `Claude Code`
    - write-side confirmed `S10 cross-client manual sentinel 2026-06-04 01.`
    - read-side wake returned the exact same truth line
  - real Cursor / router wake transcript：
    - actual routed tool call only used `wake(project_name="harness-mem", no_auto_ingest=true)`
    - routed output returned success but still used the old `# Memory Entries / # Confirmed Rules` shape
    - routed output was truncated with `[...truncated]`
    - the same parameters against repo-local wake still produced the newer layered `# Essential Truth` output
- 当前已补的 focused guards：
  - `tests/test_v2_user_test_packet_remaining_matrix_truth.py`
  - `tests/test_v2_user_test_packet_s4_transport_unavailable_truth.py`
  - `tests/test_v2_user_test_packet_wake_renderer_truth.py`
  - `tests/test_v2_user_test_packet_hermes_oneshot_truth.py`
  - `tests/test_v2_user_test_packet_ui_cross_client_truth.py`
  - `tests/test_v2_user_test_packet_cursor_router_wake_truth.py`
  - `tests/integration/test_v2_user_test_packet_wake_renderer_truth.py`
  - `tests/mcp/test_smoke.py` 中错误 launch target 的握手前失败测试

### Boundaries

- 这版现在已经有一条 `Codex app -> Claude Code` 的 UI 级 `S10` pair transcript，
  但仍**不是** Cursor 侧 `S10` 扩展证据完成。
- 这版现在已有一条真实 Cursor / router wake transcript，但仍**不是**自带工作区路径的
  `harness_mem/integration` packet run log。
- 这版也没有补齐 `S5` 或 `S7` 的真实 client transcript。
- `claude -p` 当前仍未成为稳定可用的自动化读端，所以 Hermes 这条不是跨客户端 transcript。
