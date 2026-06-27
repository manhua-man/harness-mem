# harness-mem 整体收敛审查与整改计划

**版本：v4 修正版**
**主轴：整体产品边界收敛**
**定位：session-distill 是关键专项之一，但不是本轮收敛的主轴**

目标：把稳定版默认公开面收回到 **local memory core loop**，同时保留并模块化重要能力。

> **本版纠偏**
> 前一版把 `session-distill` 专项放得过重，容易让人误解为“主轴改成 session-distill 内部特化”。本版明确改回：主轴是 **harness-mem 整体收敛**；`session-distill` 是其中一个高优先级模块，重要但不是总主题。

适用范围：MCP 工具面、插件命令面、`/hm:distill` 与 `tools/session-distill`、storage/search 架构、dream/metabolism/skill governance 等治理层、CLI 与文档默认叙事。

> **V4.2 决议更新**
> MCP 不再把 `full/minimal/core-read/review-write/labs` 作为用户需要理解的公开 profile。对外只有一个 public memory surface：读、蒸馏候选、显式 review gate、dream 默认维护。历史 `mcp_tool_profile` 请求只作为兼容噪音忽略。
>
> Dream 是默认开启的产品能力，但仍受 scheduler gate、audit ledger 和 undo metadata 约束；它不再归入 labs。Skill governance 不再作为 MCP public tools 或 harness-mem CLI 产品入口暴露；后续如果继续做，应放在 memory 产品之外的专门 skill 整理流程里。

---

## 目录

1. [执行摘要：整体收敛的主判断](#1-执行摘要整体收敛的主判断)
2. [收敛判据：保留、冻结、隔离、重构、延后](#2-收敛判据保留冻结隔离重构延后)
3. [整体优先级图：P0/P1/P2/P3](#3-整体优先级图p0p1p2p3)
4. [模块级坏味道审查](#4-模块级坏味道审查)
5. [稳定版默认公开面设计](#5-稳定版默认公开面设计)
6. [review gate 与 auto-review 策略](#6-review-gate-与-auto-review-策略)
7. [插件命令面与安装 profile](#7-插件命令面与安装-profile)
8. [session-distill：整体计划中的关键专项](#8-session-distill整体计划中的关键专项)
9. [storage/search 与 MCP/CLI 结构债](#9-storagesearch-与-mcpcli-结构债)
10. [PR/Issue 拆分计划](#10-prissue-拆分计划)
11. [验收清单与证据索引](#11-验收清单与证据索引)

---

## 1. 执行摘要：整体收敛的主判断

这份文档的主判断是：**harness-mem 目前已经有稳定主线，但实现和默认入口暴露了过多治理、维护、实验、自动化写入能力。**

现在要做的不是把某一个工具做成新主轴，而是把整个产品面重新收回到 local memory core loop。

稳定版应该承诺的主循环：

```text
wake -> search -> distill -> review
```

当前需要收敛的膨胀面：

```text
MCP full/minimal 工具面过宽
/hm:distill 默认 auto-review apply
插件命令暴露 maintenance/private workflow
session-distill 单体过胖
storage/search truth/index/vector 边界不稳
metabolism/skill governance 过早进入用户视野，knowledge-cache/wiki bridge 已超出主线
```

> **最终结论**
> 现在要 focus，不是 force。稳定版默认呈现“可读、可准备、可建议、可审查”的 local memory core loop；dream 作为默认维护能力必须可审计、可撤销。其他治理、维护、实验、自动写入能力可以保留，但必须从默认入口移走或显式开启。

---

## 2. 收敛判据：保留、冻结、隔离、重构、延后

本轮“收敛”不是简单删功能，而是给每类功能一个明确归宿。

判断标准是：它是否直接服务 `wake/search/distill/review`，是否会扩大默认信任边界，是否让用户更难理解 durable memory 从哪里来。

| 分类 | 判断标准 | 处理方式 |
|---|---|---|
| 核心保留 | 直接服务 `wake/search/distill/review`，且可审计。 | 保留并强化测试与文档。 |
| 默认冻结 | 有价值，但默认暴露会扩大产品面或信任边界。 | 从默认 profile/安装中移走，显式开启。 |
| 实验隔离 | 概念强、风险高、尚未成为稳定承诺。 | 移动到 `labs` / `maintenance` / `internal`。 |
| 结构重构 | 功能正确，但模块边界已经影响维护。 | 先锁测试，再拆模块。 |
| 延后投入 | 重要但不应在 `0.8.x` 继续堆。 | 列入 `0.9+`，不进入当前默认面。 |

### 核心保留范围

```text
wake
search_memory
prepare_session_distill
suggest_* 或 candidate draft export（受控，不直接 confirm）
list_candidates / get_candidate_detail
review / confirm / reject / replace（显式 gate）
get_project_status / doctor / setup
```

### 本轮不应继续扩张的范围

```text
metabolism / reflection_jobs
skill promotion / revision / deprecation
已删除的 knowledge-cache compact renderer
prune / mark artifact 维护链路
retrieval quality 实验层
自动 confirm / 自动 durable write
```

这些功能不是全部删除，而是降权、隔离、显式开启。

---

## 3. 整体优先级图：P0/P1/P2/P3

| 优先级 | 问题域 | 目标 | 典型改动 |
|---|---|---|---|
| P0 | 默认行为与 public contract 冲突 | 稳定版默认面可信、可解释。 | MCP 单 public memory surface；`/hm:distill` 默认 preview；`/hm:review` 成为 durable gate；Skill governance 退出 MCP public tools。 |
| P1 | 插件命令面与 session-distill 过胖 | Daily 与 artifact maintenance 分层；删除 KB/PRD 第二产品能力。 | 默认只装 `status/wake/search/search-all/distill/review/dream`；`session-distill` 只服务 candidate export。 |
| P1/P2 | storage/search 架构债 | `truth/index/vector/search facade` 边界清楚。 | 补一致性测试，再拆 `TruthStore/DerivedIndex/SearchFacade/VectorBackend`。 |
| P2 | MCP server / CLI 结构债 | 入口层不继续长成应用内核。 | `server.py` 拆 tool groups；CLI 降级为 operator console。 |
| P3 | metabolism/skill governance；已删除 knowledge-cache/wiki bridge | 保留必要治理的实验价值，但不作为稳定承诺；knowledge-cache/wiki bridge 不保留独立产品层。 | metabolism 维持受控 internal/read-debug；Skill governance 退出 MCP 和 CLI 产品面；durable knowledge 不再经过 generated cache。 |

### 关键排序原则

不要先做大重构。先修用户默认能感知到的产品边界问题。

正确顺序：

```text
先收默认公开面
-> 再修 review gate
-> 再拆插件命令面
-> 再拆 session-distill
-> 再补 storage/search 测试
-> 再做结构重构
-> 最后清理 labs/maintenance 文档叙事
```

---

## 4. 模块级坏味道审查

| 模块/功能 | 坏味道 | 决策 |
|---|---|---|
| MCP tools | 默认 `full`；`minimal` 也包含 `suggest/confirm/reject/auto_review` 等写操作。 | P0：改为单 public memory surface；不再让用户选择 profile；Skill governance 不注册为 MCP 工具。 |
| `/hm:distill auto-review` | 默认 `apply=true` 会混掉 `distill -> review` 的信任边界。 | P0：默认 preview；`apply-low-risk` 显式；`review-now` 进入 `/hm:review`。 |
| 插件命令面 | artifact maintenance、KB/PRD 管理和 Daily 命令混在一起。 | P1：Daily 默认安装 `dream`；maintenance 只保留 `mark/prune`；删除 KB/PRD command surface。 |
| `tools/session-distill` | 同时承担 packet、manifest、KB、PRD、guardrail、candidate export、cleanup，总线化。 | P1：删除 KB/PRD 管理能力，只保留 packet/candidate/export 与 artifact lifecycle。 |
| storage/search | `truth/index/vector/search facade` 双写与 optional 依赖边界不清。 | P1/P2：先补回归测试，再拆边界。 |
| storage/reflection job | 维护 store 复用 structured store 私有 `_index` 一类封装穿透。 | P1/P2：已提供 `DerivedIndex` public 边界；后续只在需要时再拆物理文件。 |
| `mcp/server.py` | God Module：transport、registry、backend lifecycle、tool specs、maintenance 混合。 | P2：拆 backend/tool groups/serializers/dispatcher。 |
| CLI | 命令面像第二产品入口。 | P2：降级为 setup/doctor/config/integration/maintenance operator console。 |
| read/context/signals | ranking、signal、sufficiency、cost strategy 容易让 read path 不可解释。 | P2：冻结默认 read contract，高级策略 behind flag 且必须 traceable。 |
| plugin bundle | 容易被误解为 canonical API 或 Claude-only 产品。 | P2：明确 plugin 是 integration bundle；canonical API 是 runtime + MCP + review lifecycle。 |
| optional native/Rust | 内部加速实现版本容易污染产品版本叙事。 | P2：对外只称 optional native acceleration；不把 native core 版本当产品版本。 |
| dream/metabolism/reflection | 将 memory backend 推向自治治理系统。 | dream 默认开启但必须有 gate/audit/undo；metabolism/reflection 仍是 maintenance/internal。 |
| skill governance | promotion/revision/deprecation 容易把项目拖成 skill lifecycle manager。 | 从 MCP public tools 与 CLI 产品入口删除；如需继续做，放到 harness-mem 之外的专门 skill 整理流程。 |

### 当前最危险的不是“大文件”，而是默认行为冲突

`mcp/server.py` 很大是结构债；但默认 `full`、`minimal` 带写操作、`auto_review apply=true` 是产品承诺冲突。

因此 P0 应该先改默认行为，而不是先拆文件。

---

## 5. 稳定版默认公开面设计

默认公开面要“单一、少而可信”。核心原则是：

```text
默认可读、可准备、可建议、可审查；
durable write 只通过显式 review gate；
dream 默认开启但必须有 scheduler gate、ledger、undo；
skill lifecycle / operator maintenance / experiment 不进入 MCP public tools。
```

| Surface | 允许能力 | 不允许能力 |
|---|---|---|
| MCP public memory surface | `wake/search/status/timeline/file_context/prepare_session_distill/suggest_* / list_candidates / get_candidate_detail / confirm_* / reject_* / supersede / dream_ledger / dream_run / dream_auto_tick / undo_dream_item`。 | `metabolism_run`, `metabolism_preview`, `health_summary`, `surface_cost_report`, `list_reflection_jobs`, `get_reflection_job`, migrations, purge/rebuild, Skill governance lifecycle tools。 |
| CLI maintenance surface | import/purge/rebuild/migrate/export/audit/operator repair。 | 不作为 Daily memory workflow；不暴露 cache、wiki bridge、bench 子产品入口；不提供可触发 metabolism 的 CLI 产品入口。 |
| Plugin Daily surface | `/hm:status`, `/hm:wake`, `/hm:search`, `/hm:search-all`, `/hm:distill`, `/hm:review`, `/hm:dream`。 | 不默认安装 raw cleanup、artifact maintenance、实验命令；不存在 KB/PRD sync 子产品。 |
| Skill governance | 不属于 harness-mem public memory 产品面；只保留 confirmed procedural memory 的 read hint 能力。 | 不作为 MCP public lifecycle tools，不混入 CLI 或 Daily `/hm:*` 命令。 |

默认用户看到的核心路径：

```text
/hm:status
/hm:wake
/hm:search
/hm:search-all
/hm:distill   # preview + candidate suggestion，不 confirm truth
/hm:review    # durable memory gate
```

### MCP 单公开面验收标准

```text
1. tools/list 只返回一个 public memory surface，不要求用户选择 full/minimal/labs/review-write。
2. auto_review_candidates(apply=true) 在 public MCP 中强制变成 preview。
3. confirm/reject/supersede 仍是显式 review gate，不由 heuristic 自动 apply。
4. 默认包含 dream 账本/显式触发/auto tick/undo，但不包含 metabolism、migration、rebuild、purge。
5. suggest_skill/confirm_skill/skill promotion/revision/deprecation 不注册为 MCP public tools。
6. 默认 tools/list 不报告 hidden maintenance tool count；历史 profile 请求只作为兼容噪音忽略，不解锁第二套 MCP 工具面。
```

---

## 6. review gate 与 auto-review 策略

`review gate` 是 harness-mem 的产品信任边界。

`distill` 可以自动整理证据、生成候选、做风险预览，但默认不应把候选直接变成 confirmed memory。

默认链路：

```text
distill
  -> suggest candidates
  -> auto_review preview
  -> /hm:review
  -> confirmed memory
```

禁止默认链路：

```text
distill
  -> auto_review apply=true
  -> confirmed memory
```

| 模式 | 行为 | 边界 |
|---|---|---|
| 默认 `/hm:distill` | 生成 packet/candidates，运行 preview。 | confirmed memory 不变。 |
| `--apply-low-risk` | 只自动处理低风险候选。 | 必须显式；必须写 audit log；不得处理 conflict/raw-review blocked。 |
| `--review-now` | distill 后进入交互式 review。 | `/hm:review` 仍是 gate。 |
| maintenance apply | mark/prune/raw cleanup 等 artifact 维护。 | 只在 maintenance profile 下可用。 |

### `/hm:distill` 的默认输出应该提示边界

建议默认 summary 明确写：

```text
Distill completed.

Candidates suggested:
- memory_entry: N
- rule: N
- task_handoff: N
- blocked/raw-review: N
- conflict-review: N

Review:
- auto-review mode: preview only
- no durable memory was confirmed
- run /hm:review to confirm/reject/replace
```

验收标准：

```text
运行 /hm:distill 后，可以新增 candidates；
但 confirmed memory 数量不能变化。
```

---

## 7. 插件命令面与安装 profile

插件命令面要按用户心智分层：

```text
Daily = 产品入口
Maintenance = 操作员工具
```

| 分组 | 命令 | 默认 |
|---|---|---|
| Daily | `/hm:status`, `/hm:wake`, `/hm:search`, `/hm:search-all`, `/hm:distill`, `/hm:review`, `/hm:dream` | 是 |
| Maintenance | `/hm:mark`, `/hm:prune` | 否，`sync-commands.ps1 -Profile Maintenance` |

安装器建议：

```powershell
.\install.ps1 -RegisterClaude
# 默认只装 Daily

.\sync-commands.ps1 -Profile Maintenance
# 不重新安装 runtime，只打开 Maintenance 命令
```

默认安装后不应该看到：

```text
/hm:mark
/hm:prune
/hm:metabolism
```

### 插件定位：integration bundle，不是 canonical API

`plugins/harness-mem` 应该被描述为 Agent client integration bundle：

```text
MCP server config
Claude Code /hm:* command files
Agent skills
PowerShell install/doctor helpers
```

它不是 harness-mem 的 canonical API。canonical API 应该是：

```text
runtime package
MCP tool contract
candidate review lifecycle
local store + audit state
```

因此文档和 README 的表达应该避免把 harness-mem 说成“Claude Code 插件”。Claude Code 插件只是默认集成体验之一；Cursor、Codex、Gemini CLI、generic MCP client 都应该共享同一条 runtime/MCP/review 边界。

---

## 8. session-distill：整体计划中的关键专项

> **定位纠偏**
> `session-distill` 很重要，但不是这份计划的主轴。它的正确位置是：整体收敛中的 P1 关键专项，用来解决“distill 工具链过胖、默认 review gate 混乱、证据到候选边界不硬”的问题。

### 8.1 内部版定位

内部 `tools/session-distill` 不应退回外部基础版；它应该继续做 harness-mem 特化。

它的最终出口应该是：

```text
harness-mem candidate lifecycle
```

而不是独立 KB、claude-mem 或某个客户端私有 memory。

主链应该是：

```text
Raw session
  -> SourceAdapter
  -> Packetizer
  -> Packet Audit
  -> CandidateDraftBuilder
  -> HarnessMemExport.suggest_*
  -> ReviewPolicy.preview
  -> /hm:review
  -> confirmed memory
```

### 8.2 职责拆分建议

建议结构：

```text
tools/session-distill/
  SKILL.md

  bin/
    session-distill.py              # thin CLI / slash command bridge

  lib/
    models.py                       # SessionSource, Packet, PacketAudit, CandidateDraft
    paths.py                        # workspace / project / client path resolution
    manifest.py                     # manifest/status lifecycle
    packet.py                       # packet generation + Packet Audit
    distill_rules.py                # stable / volatile / local-only / conflict rules
    guardrails.py                   # mark distilled / pending drafts / raw cleanup checks
    harness_mem_export.py           # candidates -> MCP suggest_*
    review_policy.py                # auto-review preview, low-risk policy, risk labels
    summary.py                      # final user-facing summary

    adapters/
      base.py                       # SourceAdapter protocol
      claude.py                     # ~/.claude/projects/*.jsonl
      codex.py                      # ~/.codex/archived_sessions + ~/.codex/sessions
      cursor.py                     # Cursor session sources
      generic_jsonl.py              # fallback adapter
      hermes.py                     # optional/internal
      opencode.py                   # optional/internal
      grok.py                       # optional/internal

    maintenance/
      raw_cleanup.py                # explicit cleanup only
      mark.py                       # mark distilled implementation

  tests/
    fixtures/
      claude/
      codex/
      cursor/
      partial_packets/
      memory_drafts/
    test_packet_audit.py
    test_adapters.py
    test_guardrails.py
    test_harness_mem_export.py
    test_review_policy.py
    test_distill_cli_default.py
    test_maintenance_commands.py
```

核心方向：

```text
bin/session-distill.py 只做薄入口；
真正能力进入 lib；
slash command 只是调用 runtime/toolchain。
```

### 8.3 外部 session-distill-skills 的吸收方式

外部 `manhua-man/session-distill-skills` 的价值是多 skill / 多阶段 / review gate / 可选协作者的分工思想。

内部不需要照搬成多个仓库，但应该吸收职责分离。

| 外部经验 | 内部吸收 |
|---|---|
| 多 skill 分离 | 内化成 adapters/profile/module 分层，不必拆多个仓库。 |
| `packet-memory-export` | 吸收 evidence -> candidate export 边界，内部实现为 `harness_mem_export.py`。 |
| Codex/Cursor/Claude 入口 | 统一 `SourceAdapter` 接口。 |
| `grill-me/answer-me/ask-me` | 作为 review-helper/labs，不写 truth。 |
| guardrail 测试经验 | 迁入内部：partial packet、pending drafts、raw cleanup、mark distilled。 |

### 8.4 `harness_mem_export` 的边界

`harness_mem_export` 是关键边界模块。

允许：

```text
suggest_memory_entry(...)
suggest_rule(...)
create_task_handoff(...)
optional: suggest_observation(...)
```

禁止：

```text
confirm_candidate(...)
reject_candidate(...)
replace_candidate(...)
auto_review_candidates(apply=true)
direct write to truth store
direct write to knowledge-base as durable truth
```

### 8.5 candidate readiness mapping

外部 `packet-memory-export` 的队列思想可以吸收进内部，但内部出口必须是 harness-mem candidate lifecycle。

建议映射：

```text
ready-candidate
  -> suggest_* + review_preview: low/medium risk

needs-raw-review
  -> suggest_* with blocked_reason = raw_review_required

needs-conflict-review
  -> suggest_* with conflict flag + require manual review

local-only
  -> session note / local artifact only，不进 harness-mem candidate

ephemeral
  -> dropped or local-only summary
```

关键约束：

```text
Packet Audit 为 partial 时，不能进入 ready/apply 路径。
local-only / ephemeral 不进入 candidate queue。
conflict 必须人工 review，不能 auto-confirm。
blocked candidate 可以被记录为 pending，但必须带 blocked_reason。
```

### 8.6 SourceAdapter 统一接口建议

```python
class SourceAdapter:
    name: str

    def discover(self, project: str | None) -> list[SessionSource]:
        ...

    def read_span(self, source: SessionSource, span: SessionSpan) -> RawSession:
        ...

    def build_packet_context(self, source: SessionSource) -> PacketContext:
        ...
```

### 8.7 `/hm:distill` 默认 summary contract

默认 summary 要把信任边界说清楚，不能让用户误以为已经写入 confirmed memory。

建议格式：

```text
Distill completed.

Packet:
- session: <session-id>
- coverage: high | partial
- raw review required: yes | no

Candidates suggested:
- memory_entry: N
- rule: N
- task_handoff: N
- local_only: N
- blocked_raw_review: N
- conflict_review: N

Review:
- auto-review mode: preview only
- no durable memory was confirmed
- run /hm:review to confirm/reject/replace
```

显式模式：

```text
/hm:distill --preview
  默认；只 preview。

/hm:distill --apply-low-risk
  只允许低风险候选进入自动处理；必须写 audit log。

/hm:distill --review-now
  distill 后进入 /hm:review 交互。

/hm:distill --maintenance
  允许调用 raw cleanup / artifact maintenance 等高级路径；必须显式；不恢复 KB/PRD 子系统。
```

### 8.8 外部同步策略

建议新增内部文档：

```text
tools/session-distill/SYNC_POLICY.md
```

定位：

```text
manhua-man/session-distill-skills
  = generic skill suite / shared workflow template

harness-mem/tools/session-distill
  = harness-mem specialized runtime integration
```

可以从外部同步：

```text
distillation rules
packet audit vocabulary
adapter parsing lessons
guardrail cases
review helper prompts
fixtures / golden packet examples
```

不能从外部直接同步：

```text
claude-mem write path
Codex-mem-specific sync behavior
external skill installation layout
memory-drafts 作为默认 promotion gate
raw deletion semantics without harness-mem guardrail
```

内部权威边界：

```text
external changes may update packet/audit/rules/adapters;
internal harness-mem export/review behavior is authoritative.
```

### 8.9 session-distill 专项测试

必须覆盖：

```text
Packet Audit high/partial
pending memory draft guardrail
local-only/ephemeral 不进入 candidate
conflict 必须人工 review
raw cleanup guardrail
/hm:distill self-session exclusion
MCP export no direct confirm
```

建议测试名：

```text
test_distill_default_does_not_confirm_truth
test_auto_review_preview_only
test_partial_packet_blocks_ready_candidate
test_harness_mem_export_only_suggests
test_distill_self_session_not_promoted
test_claude_adapter_collects_sessions
test_codex_adapter_collects_archived_and_sessions
test_cursor_adapter_collects_sessions
test_packet_audit_high_vs_partial
test_memory_drafts_pending_blocks_mark
test_mark_requires_session_note
test_kb_review_rejects_volatile_entries
test_prd_sync_dry_run_no_write
test_raw_cleanup_requires_guardrail
```

---

## 9. storage/search 与 MCP/CLI 结构债

### 9.1 storage/search

storage/search 是实质架构债，但不应在默认行为修正前先大拆。

建议先补测试，再拆边界，避免边修边继续堆 retrieval quality。

重构前先锁定不变量：

```text
1. TruthStore 是 canonical source of truth。
   confirmed memory、rule、relation、candidate 的真实状态以 canonical store 为准；
   SQLite index 只是派生读模型，不能反过来决定 truth 是否存在。

2. DerivedIndex 必须可重建。
   SQLite FTS / metadata index 丢失、损坏或升级后，系统应该能从 canonical truth
   重新构建 index；index 缺行不能导致 confirmed truth 永久不可读。

3. VectorBackend 是 optional enhancement。
   sqlite-vec、embedding model、hybrid/vector search 不可用时，core store、wake、
   basic search、candidate review 仍必须可用；vector 只能提升召回质量，不能阻断核心链路。

4. SearchFacade 拥有返回语义。
   search_memory 不能因为底层命中来自 memory entry、relation fact、skill、observation、
   vector result，就丢掉来源、状态、project scope、evidence、score/reason 等语义。

5. Project isolation 必须是结构化过滤。
   project_name / source session / scope 这类隔离条件不能靠脆弱的文本匹配或 JSON LIKE 兜底；
   应该有明确字段、索引和测试。
```

目标分层：

```text
TruthStore        # canonical durable memory
CandidateStore    # candidate / review lifecycle
ObservationStore  # raw/session/verbatim material, explicit project boundary
DerivedIndex      # SQLite/search index, rebuildable
VectorBackend     # optional enhancement, cannot block core store
SearchFacade      # read path facade, owns return semantics
```

需要补的回归测试：

```text
canonical truth 与 SQLite derived index 一致性：
- confirmed truth 写入后 index 有对应派生行。
- index 缺行时，truth 仍可通过 canonical path 读取。
- rebuild index 后 search 结果恢复。

optional vector backend 不可用时 core store 不被阻断：
- sqlite-vec 不可用时 init/store/wake/basic search 不失败。
- embedding model 禁用或加载失败时，FTS/search fallback 可用。

search_memory 返回语义不可丢：
- memory_entry 命中保留 category/status/source/evidence。
- relation_fact 命中保留 source_entity/target_entity/relation_type/confidence。
- skill 命中保留 activation/steps/scope/origin_project。
- observation 命中保留 session/source/project metadata。
- recall contract 中 evidence/source/step/status 稳定。

project isolation 使用结构化字段：
- scope=project 不返回其它 project 的 observation/truth。
- scope=all 返回时必须按 project_name 可辨识。
- 不依赖 JSON LIKE 匹配 project_name。

candidate review 后索引同步：
- confirm/reject/supersede 后 candidate status 与 confirmed truth/index 同步。
- confirmed memory 进入 wake/search；rejected/pending 不进入 confirmed 结果。
```

核心原则：

```text
index 可以丢、可以重建；
truth 不能被 index 反向绑架。
```

#### storage/reflection job 封装边界

短期要先消除封装穿透，而不是直接大拆 store。坏味道示例：

```text
LocalMemoryBackend -> LocalStructuredStore._index
```

`_index` 是 structured store 的私有实现细节；如果 reflection job、maintenance job 或 migration 需要共享 index 生命周期，应该通过显式边界表达。

可接受方案：

```text
方案 A：LocalStructuredStore 提供受控 public index property。
方案 B：LocalMemoryBackend 显式创建 shared IndexStore，并注入 StructuredStore / ReflectionJobStore。
方案 C：把 IndexStore 作为独立 owner，TruthStore / CandidateStore / ReflectionJobStore 只依赖接口。
```

验收标准：

```text
没有模块访问其它模块的 private attribute。
reflection job 生命周期不污染 runtime bootstrap。
migration/rebuild index 有明确 owner。
candidate/review/audit 语义不因 index 复用而改变。
```

### 9.2 MCP server

`mcp/server.py` 的问题是结构债，不是第一优先级，但必须进入 P2。

建议拆分：

```text
harness_mem/mcp/server.py          # stdio / JSON-RPC / dispatch
harness_mem/mcp/backend.py         # backend lifecycle
harness_mem/mcp/executor.py        # tools/call execution policy
harness_mem/mcp/serializers.py     # result serialization
harness_mem/mcp/tool_registry.py   # profile / registry / permissions
harness_mem/mcp/tool_handlers.py   # MCP tool handler implementations
harness_mem/mcp/tools/read.py      # wake/search/status/profile/rules
harness_mem/mcp/tools/distill.py   # prepare_session_distill / suggest-only export
harness_mem/mcp/tools/review.py    # list/detail/confirm/reject/replace
harness_mem/mcp/tools/maintenance.py
harness_mem/mcp/tools/labs.py
harness_mem/mcp/tools/admin.py
```

### 9.3 CLI

CLI 不应成为第二套完整产品入口。

保留为 operator console：

```text
hm init
hm quickstart
hm doctor
hm config
hm integration
hm maintenance
```

V4.1 进一步收敛 CLI surface：旧顶层 `hm import` / `hm purge` 不保留
deprecated alias，维护能力下沉为 `hm maintenance import` 与
`hm maintenance purge`。两者默认 dry-run，只有显式 `--apply` 才写
candidate layer 或执行 soft-delete。本轮不新增 `debug` 顶层命令，避免为了
收敛反而扩大 public surface。

避免 CLI 和 MCP 同时长成两套完整应用。

### 9.4 read/context/signals

read path 的默认体验必须 simple、deterministic、traceable。

可以保留高级策略：

```text
retrieval_profile=quality
signal_influence=on
context_sufficiency=diagnostic
cost_budget_policy=diagnostic
已删除的 knowledge-cache compact renderer
```

但它们不能改变默认 public read contract。默认 contract 应固定为：

```text
wake(project)
search_memory(query)
get_project_status(project)
get_confirmed_rules(project)
get_task_handoffs(project)
get_observations(session/project)
```

高级策略的验收标准：

```text
默认关闭或由显式配置 opt-in；dream 例外，它是默认开启但受 scheduler gate/audit/undo 约束的维护能力。
输出包含 trace / reason / evidence，不制造黑盒 ranking。
关闭高级策略后，wake/search 的基础结果仍可解释、可审计。
不把 signal/sufficiency/cost policy 写成 quickstart 主路径。
```

### 9.5 optional native/Rust acceleration

Rust/native 能力应被定位为 optional acceleration，不是产品版本叙事。

对外表达：

```text
optional native acceleration
optional Rust acceleration
Python-only fallback
```

避免表达：

```text
native core vX as product version
Rust core as required architecture promise
Python path as second-class fallback
```

验收标准：

```text
package version 是唯一对外产品版本。
Python-only path 可安装、可测试、可运行 core loop。
native/Rust 不可用时 wake/search/distill/review 不被阻断。
README/quickstart 不用 native core 大版本解释产品边界。
```

---

## 10. PR/Issue 拆分计划

PR 顺序按“先收默认行为，再拆工具链，再补存储测试，最后整理 maintenance/internal 文档”的顺序执行。

每个 PR 都应该小而可验收，避免把 `session-distill` 专项重新变成总线式大改。

### PR-1：MCP 单 public memory surface 收敛

目标：

```text
不再让用户选择 full/minimal/review/labs profile；public MCP 只有一个 memory surface。
```

验收：

```text
工具列表包含 read/distill candidate/review gate/dream；
auto_review apply 强制 preview；
Skill governance 不注册为 MCP public tools。
```

---

### PR-2：`/hm:distill` review gate 修正

目标：

```text
auto-review 默认 preview；apply-low-risk 显式。
```

验收：

```text
运行 distill 后 confirmed memory 数量不变。
默认 summary 明确显示 auto-review mode: preview only。
Packet coverage、raw review required、candidate counts、blocked/conflict/local-only 数量可见。
```

---

### PR-3：插件命令分层

目标：

```text
Daily 默认；artifact maintenance 显式安装；KB/PRD 管理命令不存在。
```

验收：

```text
默认安装看不到 mark/prune；默认安装包含 dream；KB/PRD 管理入口不存在。
```

---

### PR-4：session-distill freeze + 薄入口

目标：

```text
禁止继续扩张；拆 models/paths/packet/manifest/distill_rules/guardrails/export/review_policy/summary。
bin/session-distill.py 只保留参数解析和 lib 调用。
```

验收：

```text
旧命令可跑，核心函数可单测。
packet audit、guardrails、export、review policy 不依赖 CLI 进程状态。
新增或预留 tools/session-distill/SYNC_POLICY.md，明确外部 skill suite 与内部 specialization 的同步规则。
```

---

### PR-5：SourceAdapter 统一

目标：

```text
Claude/Codex/Cursor/generic 使用同一接口。
```

验收：

```text
同一 packetizer 可处理多客户端 fixtures。
```

---

### PR-6：harness_mem_export 边界

目标：

```text
candidate draft -> suggest_*；禁止 confirm/direct truth write。
实现 ready-candidate / needs-raw-review / needs-conflict-review / local-only / ephemeral 映射。
```

验收：

```text
未 review 的 candidate 不进入 wake/search confirmed 结果。
partial packet 不能进入 ready/apply 路径。
blocked/conflict candidate 必须携带 blocked_reason 或 conflict flag。
local-only/ephemeral 不进入 harness-mem candidate queue。
```

---

### PR-7：信任边界测试

目标：

```text
覆盖 Packet Audit、pending drafts、raw cleanup、removed KB/PRD commands、self-session exclusion。
覆盖默认 preview、export only suggest、readiness mapping、adapter fixtures。
```

验收：

```text
默认链路不会绕过 review gate。
至少包含 test_distill_default_does_not_confirm_truth、test_auto_review_preview_only、
test_partial_packet_blocks_ready_candidate、test_harness_mem_export_only_suggests、
test_distill_self_session_not_promoted。
```

---

### PR-8：storage/search 回归测试

目标：

```text
补 truth/index/vector/search facade 一致性测试，先锁定 storage/search 不变量。
```

验收：

```text
测试先于重构合入。
覆盖 canonical truth / derived index 同步与 index rebuild。
覆盖 storage/reflection job 不再访问其它 store 的 private attribute。
覆盖 vector backend 不可用时 core loop 仍可用。
覆盖 search_memory 对 memory/relation/skill/observation 命中的稳定返回语义。
覆盖 scope=project / scope=all 的 project isolation。
覆盖 candidate review 后 confirmed/pending/rejected 的搜索可见性。
```

---

### PR-9：storage/search 边界重构

目标：

```text
拆 TruthStore/DerivedIndex/SearchFacade/VectorBackend 等。
```

验收：

```text
index 可重建；truth 不依赖 index。
IndexStore 或等价边界有明确 owner；无 `_structured_store._index` 一类穿透。
VectorBackend 不阻断 wake/search/review。
SearchFacade 输出 contract 与 PR-8 测试保持一致。
project isolation 不靠 JSON LIKE 或文本兜底。
```

---

### PR-10：maintenance/internal 降权与文档清理

目标：

```text
metabolism/skill governance 移出默认路径；knowledge-cache/wiki bridge 从 runtime package 删除；dream 保留默认入口但必须可审计、可撤销。
read/context/signals 高级策略不进入 quickstart 主路径。
plugin 文档明确 integration bundle，不冒充 canonical API。
native/Rust 只作为 optional acceleration 叙事。
```

验收：

```text
README/quickstart 只讲核心闭环。
plugin README 不把 harness-mem 定义成 Claude-only 插件。
高级 read strategy 有显式 opt-in 与 trace，不改变默认 read contract。
package version 是唯一对外产品版本；native/Rust 不阻断 Python-only core loop。
```

---

### Issue 标题建议

```text
[P0] Collapse MCP profiles into one public memory surface
[P0] Remove Skill governance from MCP public tools
[P0] Make /hm:distill auto-review preview-only by default
[P1] Split Daily and Maintenance slash command installation
[P1] Refactor tools/session-distill into thin CLI plus lib modules
[P1] Add session-distill readiness mapping and default summary contract
[P1] Add harness_mem_export suggest-only boundary
[P1] Add session-distill external sync policy
[P1] Add distill/review gate regression tests
[P2] Add storage/search consistency tests before refactor
[done] Remove private _index coupling from storage/reflection jobs
[P2] Split MCP server tool groups
[P2] Freeze default read contract and gate advanced strategy behind flags
[P2] Clarify plugin as integration bundle, not canonical API
[P2] Keep native/Rust acceleration optional in public docs
[P3] Keep metabolism internal and remove Skill governance from harness-mem public product surfaces
```

---

## 11. 验收清单与证据索引

### Definition of Done

本轮整体收敛完成的判断标准：

- 默认公开面只展示 local memory core loop。
- MCP 不要求用户选择 profile；public memory surface 不包含 auto apply、operator maintenance 或 Skill governance lifecycle tools。
- `/hm:distill` 默认 preview，不 confirm durable memory。
- `/hm:review` 是用户可理解、可审计的唯一持久化 gate。
- Daily / Maintenance 命令已分层，Daily 包含 dream；KB/PRD 产品管理命令已删除。
- `session-distill` 作为 P1 专项完成薄入口和 lib 拆分，但没有成为产品主轴。
- `session-distill` 有明确 readiness mapping、default summary contract 和外部同步策略。
- `harness_mem_export` 只能 suggest，不能 confirm/reject/replace/direct truth write。
- storage/search 已有一致性测试保护，并已启动 TruthStore/CandidateStore 首轮边界拆分。
- storage/reflection job 通过 `DerivedIndex` public 边界复用 structured index，不再访问其它 store 的 private attribute。
- read/context/signals 的高级策略默认不改变 wake/search 的稳定 contract。
- plugin 被表述为 integration bundle，不是 canonical API 或 Claude-only 产品。
- native/Rust 被表述为 optional acceleration，不污染 package version 叙事。
- metabolism 不出现在 README/quickstart 主路径；knowledge-cache/wiki bridge 不作为仓库 runtime 能力保留；dream 作为默认能力出现在 Daily 路径。
- metabolism/reflection jobs 保留为内部后台治理机制；默认产品/MCP/slash 不解释这些概念，只通过受控 maintenance read/debug 通道查看审计状态。
- Skill governance 不进入 MCP lifecycle tools、CLI 顶层命令或 Daily `/hm:*`；
  confirmed procedural memory 只作为 read hint 被使用。

### 证据索引

以下路径/行号来自本次讨论中提供的本地证据，落 PR 前建议在本地重新 grep 与测试确认。

| 主题 | 证据/路径 |
|---|---|
| MCP 单公开面与工具面 | `harness_mem/mcp/tool_specs.py:PUBLIC_MCP_TOOL_NAMES`; `harness_mem/mcp/tool_registry.py:resolve_mcp_tool_profile`; `harness_mem/mcp/executor.py:execute_tool_call`; `tests/test_mcp_tool_profile_contract.py` |
| session-distill 薄入口 | `tools/session-distill/bin/session-distill.py`; `tools/session-distill/lib/cli.py`; `tools/session-distill/lib/cli_handlers/` |
| SourceAdapter 统一 | `tools/session-distill/lib/adapters/clients.py`; `tools/session-distill/lib/packet.py`; `tests/test_session_distill_adapters.py` |
| review gate 与 auto-review 冲突 | `plugins/harness-mem/commands/hm/daily/distill.md`; `tools/session-distill/SKILL.md`; `tests/test_mcp_tool_profile_contract.py` |
| session-distill summary contract | `tools/session-distill/lib/summary.py`; `tests/test_session_distill_boundaries.py` |
| harness_mem_export suggest-only 边界 | `tools/session-distill/lib/harness_mem_export.py`; `tests/test_session_distill_boundaries.py` |
| removed KB/PRD command guardrails 与 raw cleanup guardrails | `tools/session-distill/lib/cli.py`; `tests/test_session_distill_cli_guardrails.py` |
| storage/search 不变量 | `tests/test_storage_search_invariants.py` |
| storage truth/candidate 边界 | `harness_mem/storage/truth_store.py`; `harness_mem/storage/candidate_store.py`; `harness_mem/storage/local_structured_store.py` |
| storage derived index 边界 | `harness_mem/storage/derived_index.py`; `harness_mem/storage/local_structured_store.py:index`; `harness_mem/storage/local_verbatim_store.py:index`; `harness_mem/storage/reflection_job_store.py`; `harness_mem/storage/sqlite_index.py:locked_connection`; `tests/test_storage_search_invariants.py:test_reflection_jobs_use_public_derived_index_boundary` |
| SearchFacade 边界 | `harness_mem/search/backend.py:SearchFacade`; `tests/test_storage_search_invariants.py` |
| Skill governance 移除证据 | `tests/test_cli_surface.py`; `tests/test_mcp_tool_profile_contract.py`; `harness_mem/mcp/tool_specs.py` |
| optional vector fallback | `harness_mem/search/hybrid_search.py`; `tests/test_storage_search_invariants.py:test_vector_disabled_hybrid_search_falls_back_to_fts` |
| CLI operator console 定位 | `harness_mem/cli.py:3`; `harness_mem/cli.py:141` |
| read/context/signals 策略层 | `harness_mem/mcp/tool_specs.py:111`; `harness_mem/task_context_runtime.py:8`; `harness_mem/context_assembly.py:365` |
| optional native/Rust 边界 | `Cargo.toml:2`; `crates/harness_mem_core_rs/Cargo.toml:2`; `pyproject.toml:63` |
| 外部 skill suite | `https://github.com/manhua-man/session-distill-skills` |
| harness-mem 主仓 | `https://github.com/manhua-man/harness-mem` |

---

## 最终表述

整体收敛是主轴；`session-distill` 是关键专项。

稳定版要把默认公开面收回 local memory core loop，实验、维护、治理、自动写入能力可以保留，但必须降权、隔离、显式开启。

执行上直接按 V4 改：

```text
1. 以 V4 为唯一 implementation baseline。
2. 冲突时听 V4，不听 V1/V2/V3。
3. 先改默认行为，再拆结构债。
4. 先收 public surface，再重构内部模块。
5. stable 默认不自动写 durable memory。
6. dream 默认开启但必须 gate/audit/undo；maintenance / governance / metabolism 默认隐藏或内部化。
```
