# Roadmap: harness-mem v2.9

> 状态：v2.9.0 / v2.9.1 / v2.9.2 / v2.9.3 / v2.9.4 / v2.9.5 / v2.9.6 / v2.9.7 / v2.9.8 已完成。
>
> 主题：PRD Sync Candidate Surface。把已有的 `prd-sync` 半成品脚本收束成
> 正式的 `/hm:prd-sync` 维护入口：默认 dry-run，只生成 candidate，不直接改
> PRD/roadmap 或 confirmed truth。

---

## 目标

当前 repo 已经在 `tools/session-distill/bin/session-distill.py` 里放了一个
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

- 已完成 `openspec/changes/v290-prd-sync-candidate-surface/`。
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

- 已完成 `openspec/changes/v291-status-triage-surface/`。
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

- 已完成 `openspec/changes/v292-plugin-doctor-helper-integrity/`。
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

- 已完成 `openspec/changes/v293-cli-maintenance-surface-truth/`。
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

- 已完成 `openspec/changes/v294-stale-cli-surface-guard-sync/`。
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

- 已完成 `openspec/changes/v295-shell-completion-maintenance-truth/`。
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

- 已完成 `openspec/changes/v296-maintenance-surface-collateral-sync/`。
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

- 已完成 `openspec/changes/v297-maintenance-surface-readme-and-telemetry-sync/`。
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

- 已完成 `openspec/changes/v298-maintenance-surface-collateral-guard/`。
- 新增 `tests/test_maintenance_surface_collateral.py`，覆盖：
  - README maintenance-console summary
  - MCP spec maintenance surface summary
  - telemetry spec maintenance surface summary
  - v2 user-test packet 的允许维护命令 summary
- 该切片不改 runtime surface，只给现有 collateral truth 加回归护栏。
