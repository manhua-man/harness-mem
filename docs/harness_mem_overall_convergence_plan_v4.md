# harness-mem 整体收敛审查与整改计划

**版本：v4 修正版**
**主轴：整体收敛状态与剩余整改计划**
**定位：session-distill 是关键专项之一，但不是本轮收敛的主轴**

目标：把稳定版默认公开面收回到 **Agent memory runtime core loop**，同时记录哪些功能已经删除、哪些边界已经收住、哪些代码结构债仍需继续收敛。

> **本版纠偏**
> 前一版把 `session-distill` 专项放得过重，容易让人误解为“主轴改成 session-distill 内部特化”。本版明确改回：主轴是 **harness-mem 整体收敛**；`session-distill` 是其中一个高优先级模块，重要但不是总主题。

适用范围：MCP 工具面、插件命令面、`/hm:distill` 与 `tools/session-distill`、storage/search 架构、dream 与已删除 M07X standalone 维护面、Skill governance 等治理层、CLI 与文档默认叙事。

> **V4.2 决议更新**
> MCP 不再把 `full/minimal/core-read/review-write/labs` 作为用户需要理解的公开 profile。对外只有一个 public memory surface：读、蒸馏候选、显式 review gate、dream 默认维护。历史 MCP profile 参数、env gate 和 degraded 兼容解释已经删除。
>
> Dream 是默认开启的产品能力，但仍受 dream auto gate、audit ledger 和 undo metadata 约束；它不再归入 labs。Skill governance 不再作为 MCP public tools 或 harness-mem CLI 产品入口暴露；后续如果继续做，应放在 memory 产品之外的专门 skill 整理流程里。

## 0. 当前状态快照

这份文档现在不是“未执行计划原文”，而是当前收敛状态和剩余改进计划的基线。按当前代码与提交状态，应这样理解：

### 已闭环

```text
MCP: 单一 public memory surface；历史 MCP profile 参数、env gate、degraded 解释已删除。
MCP registry: 只注册 public memory tools；非 public 工具不再先注册再 hidden。
/hm:distill: 默认 preview；auto-review 不默认写 durable truth。
Dream: 默认产品能力；保留 auto gate / ledger / undo 边界。
Skill governance: 退出 MCP、CLI 顶层和 Daily slash commands。
CLI: 退回 setup / doctor / config / integration / maintenance operator console。
M10: knowledge-cache / wiki bridge / compact renderer runtime 已删除。
causal benchmark: 不再作为 CLI/runtime 产品面暴露。
Plugin: Daily 默认包含 status/wake/search/search-all/distill/review/dream。
Plugin maintenance slash: /hm:mark 与 /hm:prune 用户可见入口已删除；只保留内部 guardrail helper。
Storage/search: 已落 TruthStore / CandidateStore / DerivedIndex 不变量测试，并补上 record payload 边界，拆出的 store 不再访问 LocalStructuredStore._blob_path。
```

### 尚未完全闭环

```text
MCP handlers: tool_handlers.py 仍偏大；后续可继续拆 handler group，但不是 public contract 漏口。
storage/search: LocalStructuredStore 仍是兼容 facade，内部职责还要继续向 TruthStore / CandidateStore / DerivedIndex / SearchFacade 下沉。
read/context/signals: 默认 contract 已收住，但高级策略、trace、cost/sufficiency 仍需继续冻结边界和删无测试分支。
standalone maintenance/metabolism/reflection: 产品面已收，但内部命名和最小实现仍需继续并入 dream/background job 语义。
文档: V4 需要持续区分 Done / Remaining / Removed，避免旧计划语言被误读成仍待执行。
```

### 后续处理原则

```text
能删的删：没有 public surface、没有内部调用、没有测试价值的旧能力直接删除。
能合的合：重复治理概念并入 dream / background job / review gate。
必须保留的收边界：storage/search/read path 不硬删核心能力，但要减少 facade 内部职责和隐式副作用。
```

---

## 目录

0. [当前状态快照](#0-当前状态快照)
1. [执行摘要：整体收敛的主判断](#1-执行摘要整体收敛的主判断)
2. [收敛判据：保留、冻结、隔离、重构、延后](#2-收敛判据保留冻结隔离重构延后)
3. [整体优先级图：P0/P1/P2/P3](#3-整体优先级图p0p1p2p3)
4. [模块级坏味道审查](#4-模块级坏味道审查)
5. [稳定版默认公开面设计](#5-稳定版默认公开面设计)
6. [review gate 与 auto-review 策略](#6-review-gate-与-auto-review-策略)
7. [插件命令面与命令可见性](#7-插件命令面与命令可见性)
8. [session-distill：整体计划中的关键专项](#8-session-distill整体计划中的关键专项)
9. [storage/search 与 MCP/CLI 结构债](#9-storagesearch-与-mcpcli-结构债)
10. [改进计划：按状态执行](#10-改进计划按状态执行)
11. [验收清单与证据索引](#11-验收清单与证据索引)

---

## 1. 执行摘要：整体收敛的主判断

这份文档的主判断是：**harness-mem 目前已经有稳定主线，但实现和默认入口暴露了过多治理、维护、实验、自动化写入能力。**

现在要做的不是把某一个工具做成新主轴，而是把整个产品面重新收回到 local memory core loop。

稳定版应该承诺的主循环：

```text
wake -> search -> distill -> review
```

本轮从这些膨胀面开始收敛；当前应按状态理解：

```text
[done] 历史 MCP full/minimal 工具面过宽 -> 已收为单 public memory surface。
[done] /hm:distill 默认 auto-review apply -> 已改为默认 preview / review gate。
[done] 插件默认命令面过宽 -> Daily 默认包含 dream，不默认暴露维护命令。
[remaining] session-distill 单体仍偏胖 -> 继续拆薄入口和 lib 边界。
[remaining] storage/search truth/index/vector 边界仍需继续下沉。
[done/remaining] standalone metabolism/reflection、Skill governance、knowledge-cache/wiki bridge 已退出产品面；内部命名、遗留 schema/store 痕迹继续清理。
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
| 默认冻结 | 有价值，但默认暴露会扩大产品面或信任边界。 | 从默认可见面/安装中移走，显式开启。 |
| 实验隔离 | 概念强、风险高、尚未成为稳定承诺。 | 移到 internal、独立专项或显式 maintenance，不进入 public MCP。 |
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
已删除 standalone metabolism / reflection debug 面
skill promotion / revision / deprecation
已删除的 knowledge-cache compact renderer
prune / mark artifact 维护链路
retrieval quality 实验层
自动 confirm / 自动 durable write
```

这些功能不是全部保留后换入口。没有明确核心价值、调用方和测试价值的旧能力直接删除；确有价值但不适合作为默认 memory workflow 的能力，才降权、隔离或显式开启。

---

## 3. 整体优先级图：P0/P1/P2/P3

| 优先级 | 问题域 | 目标 | 典型改动 |
|---|---|---|---|
| P0 | 默认行为与 public contract 冲突 | 已闭环；继续用测试守边界。 | MCP 单 public memory surface；`/hm:distill` 默认 preview；`/hm:review` 成为 durable gate；Skill governance 退出 MCP public tools。 |
| P1 | 插件命令面与 session-distill 过胖 | 默认面已收；继续删除无用 slash/artifact 维护能力。 | 默认只装 `status/wake/search/search-all/distill/review/dream`；`session-distill` 只服务 candidate export。 |
| P1/P2 | storage/search 架构债 | 第一刀已落；继续把 facade 内部职责下沉。 | 已补一致性测试；继续拆 `TruthStore/DerivedIndex/SearchFacade/VectorBackend`。 |
| P2 | MCP server / CLI 结构债 | CLI public 面已收；MCP 内部 handler 继续瘦身。 | registry 只注册 public memory tools；CLI 保持 operator console。 |
| P3 | 已删除 standalone M07X metabolism/reflection；Skill governance；已删除 M10 knowledge-cache/wiki bridge | 产品面已收；继续删内部命名和无调用痕迹。 | dream 保留默认入口、auto gate、ledger、undo；底层扫描/ledger 仅作为 dream 内部实现；Skill governance 不进入 memory MCP/CLI。 |

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
-> 最后清理 maintenance/internal 文档叙事
```

---

## 4. 模块级坏味道审查

| 模块/功能 | 坏味道 | 决策 |
|---|---|---|
| MCP tools | 历史默认 `full`；`minimal` 也包含 `suggest/confirm/reject/auto_review` 等写操作。 | 已完成 P0：改为单 public memory surface；不再让用户选择 profile；Skill governance 不注册为 MCP 工具。 |
| `/hm:distill auto-review` | 历史默认 `apply=true` 会混掉 `distill -> review` 的信任边界。 | 已完成 P0：默认 preview；`apply-low-risk` 显式；`review-now` 进入 `/hm:review`。 |
| 插件命令面 | artifact maintenance、KB/PRD 管理和 Daily 命令混在一起。 | 默认面已完成：Daily 默认安装 `dream`；后续继续删除不必要的高级 slash/artifact 命令，而不是靠更多分组膨胀。 |
| `tools/session-distill` | 同时承担 packet、manifest、KB、PRD、guardrail、candidate export、cleanup，总线化。 | P1：删除 KB/PRD 管理能力，只保留 packet/candidate/export 与 artifact lifecycle。 |
| storage/search | `truth/index/vector/search facade` 双写与 optional 依赖边界不清。 | P1/P2：先补回归测试，再拆边界。 |
| storage/reflection job | 维护 store 复用 structured store 私有 `_index` 一类封装穿透。 | P1/P2：已提供 `DerivedIndex` public 边界；后续只在需要时再拆物理文件。 |
| `mcp/server.py` | God Module：transport、registry、backend lifecycle、tool specs、maintenance 混合。 | P2：拆 backend/tool groups/serializers/dispatcher。 |
| CLI | 命令面像第二产品入口。 | P2：降级为 setup/doctor/config/integration/maintenance operator console。 |
| read/context/signals | ranking、signal、sufficiency、cost strategy 容易让 read path 不可解释。 | P2：冻结默认 read contract，高级策略 behind flag 且必须 traceable。 |
| plugin bundle | 容易被误解为 canonical API 或 Claude-only 产品。 | P2：明确 plugin 是 integration bundle；canonical API 是 runtime + MCP + review lifecycle。 |
| optional native/Rust | 内部加速实现版本容易污染产品版本叙事。 | P2：对外只称 optional native acceleration；不把 native core 版本当产品版本。 |
| dream 与已删除 M07X standalone 维护面 | 旧实现将 memory backend 推向多套自治治理系统。 | dream 是唯一自动维护产品能力，必须有 gate/audit/undo；standalone metabolism/reflection MCP/CLI/slash/read-debug 面删除。 |
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
dream 默认开启但必须有 auto gate、ledger、undo；
skill lifecycle / operator maintenance / experiment 不进入 MCP public tools。
```

| Surface | 允许能力 | 不允许能力 |
|---|---|---|
| MCP public memory surface | `wake/search/status/timeline/file_context/prepare_session_distill/suggest_* / list_candidates / get_candidate_detail / confirm_* / reject_* / supersede / dream_ledger / dream_run / dream_auto_tick / undo_dream_item`。 | 已删除 standalone metabolism/reflection/read-debug tools；不暴露 migrations、purge/rebuild、Skill governance lifecycle tools。 |
| CLI maintenance surface | import/purge/rebuild/migrate/export/audit/operator repair。 | 不作为 Daily memory workflow；不暴露 cache、wiki bridge、bench 子产品入口；不提供 standalone 后台维护触发入口。 |
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
1. tools/list 只返回一个 public memory surface，不要求用户理解或选择历史 full/minimal/labs/review-write 分组。
2. auto_review_candidates(apply=true) 在 public MCP 中强制变成 preview。
3. confirm/reject/supersede 仍是显式 review gate，不由 heuristic 自动 apply。
4. 默认包含 dream 账本/显式触发/auto tick/undo，但不包含 standalone metabolism/reflection、migration、rebuild、purge。
5. suggest_skill/confirm_skill/skill promotion/revision/deprecation 不注册为 MCP public tools。
6. 默认 tools/list 不报告 hidden maintenance tool count；历史 MCP profile 参数、env gate、degraded 兼容解释已删除。
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
| maintenance apply | mark/prune/raw cleanup 等 artifact 维护。 | 只在显式 maintenance 命令下可用。 |

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

## 7. 插件命令面与命令可见性

插件命令面要按用户心智收窄：

```text
Daily = 产品入口
历史 Maintenance slash = 已删除用户可见入口
```

| 分组 | 命令 | 默认 |
|---|---|---|
| Daily | `/hm:status`, `/hm:wake`, `/hm:search`, `/hm:search-all`, `/hm:distill`, `/hm:review`, `/hm:dream` | 是 |

安装器建议：

```powershell
.\install.ps1 -RegisterClaude
# 默认只装 Daily
```

安装或同步后不应该看到：

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
| 多 skill 分离 | 内化成 adapters/source/module 分层，不必拆多个仓库，也不重新引入用户可见 profile。 |
| `packet-memory-export` | 吸收 evidence -> candidate export 边界，内部实现为 `harness_mem_export.py`。 |
| Codex/Cursor/Claude 入口 | 统一 `SourceAdapter` 接口。 |
| `grill-me/answer-me/ask-me` | 最多作为 internal review-helper，不写 truth，不进入 Daily 或 MCP public memory surface。 |
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
harness_mem/mcp/tool_registry.py   # public memory registry / visibility
harness_mem/mcp/tool_handlers.py   # temporary compatibility facade while groups split out
harness_mem/mcp/tools/read.py      # wake/search/status/project/rules
harness_mem/mcp/tools/distill.py   # prepare_session_distill / suggest-only export
harness_mem/mcp/tools/review.py    # list/detail/confirm/reject/replace
harness_mem/mcp/tools/dream.py     # dream ledger/run/tick/undo
```

MCP registry 不应再保留 hidden internal/admin ToolSpec。确实需要的内部能力应放在 runtime 内部 API、CLI maintenance 或 dream/background job 实现层，而不是先注册成 MCP tool 再隐藏。

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
retrieval_mode=quality  # 如果代码内部仍叫 retrieval_profile，只作为内部配置名，不进入用户心智模型。
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
默认关闭或由显式配置 opt-in；dream 例外，它是默认开启但受 auto gate/audit/undo 约束的维护能力。
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

## 10. 改进计划：按状态执行

不要再把早期 PR 列表当作未完成 backlog。当前计划按 Done / P0 / P1 / P2 管理；P0 是 public contract，P1/P2 是继续代码收敛和删除遗留。

### Done：已闭环，不再反复设计

```text
[done] MCP 单 public memory surface：不再要求用户选择 full/minimal/core-read/review-write/labs。
[done] Skill governance 退出 memory MCP、harness-mem CLI 产品入口和 Daily slash commands。
[done] Dream 是默认产品能力，进入 Daily；保留 auto gate、audit ledger、undo metadata。
[done] /hm:distill 默认 preview；durable write 继续走 /hm:review。
[done] CLI 退回 operator console；旧顶层 import/purge 已下沉到 maintenance。
[done] M10 knowledge-cache / wiki bridge / compact renderer runtime 删除。
[done] causal benchmark 不作为 CLI/runtime 产品面暴露。
[done] /hm:mark 与 /hm:prune 外部入口删除；session-distill artifact lifecycle 只保留内部 guardrail helper。
[done] MCP registry 只注册 public memory tools；update_project_profile 不再作为 MCP tool。
[done] storage/search 已落 TruthStore / CandidateStore / DerivedIndex 不变量测试和 record payload 边界。
```

### P0：本文档与 public contract 守护

目标：

```text
文档必须准确反映当前状态，不把已删除或已收敛的旧入口写成仍待执行。
对用户只讲一个 public memory surface，不再解释 profile、labs 或隐藏工具数量。
```

验收：

```text
历史 full/minimal/labs/review-write 只作为“已删除背景”出现。
P0 项目全部标为 done 或 public-contract guard，不再挂在待办列表里。
Dream 默认开启的叙事与 review gate/audit/undo 一致。
Skill governance 的后续归宿明确为 memory MCP 之外的专项流程，而不是 hidden MCP tool。
```

### P1：继续做代码收敛与多余功能移除

下一轮优先处理“还有代码痕迹但不该形成产品心智”的部分：

```text
1. Skill governance 残留清理
   promotion/revision/deprecation 的 schema、serializer、store 若没有非 MCP 调用方，直接删除。
   如确实要保留，迁到独立 skill-governance / skill-optimizer 专项，不进 harness-mem memory MCP。

2. Dream / background job 命名合并
   standalone metabolism/reflection 产品面已删；内部命名继续并入 dream/background job 语义。
   用户只理解 dream 默认维护，不理解第二套 maintenance/metabolism 系统。

3. session-distill 瘦身
   保留 packet -> candidate draft -> suggest-only export -> review gate。
   删除 KB/PRD 第二产品能力；artifact lifecycle 用户入口已删，只保留内部 guardrail helper。

4. Plugin / slash command 收窄
   Daily 保留 status/wake/search/search-all/distill/review/dream。
   不再用高级 slash profile 承载维护能力；确需维护走 CLI operator 或内部 helper。
```

### P2：storage/search/read 继续拆边界

storage/search 不适合粗暴删除，因为它是 core memory runtime 的底座。处理方式是先守不变量，再继续减 facade 职责：

```text
1. LocalStructuredStore 继续降为兼容 facade。
2. TruthStore 持有 canonical truth；CandidateStore 持有 pending/rejected/review lifecycle。
3. DerivedIndex / SearchFacade 持有可重建 index 与 search 返回 contract。
4. Vector/embedding 永远不能阻塞 init/store/wake/basic search。
5. read/context/signals 冻结默认 contract；无测试、无 trace、无明确调用方的策略分支删除。
```

验收：

```text
truth 不依赖 index 存在。
index 可删可重建。
vector backend 不可用时 core loop 仍可用。
SearchFacade 不丢 source_kind/source_id/project_name/truth_status/preview/hydrate 语义。
scope=all 仍保留 project identity；project isolation 不靠文本兜底。
```

### Issue 状态清单

```text
[done] Collapse MCP profiles into one public memory surface
[done] Remove Skill governance from MCP public tools
[done] Make /hm:distill auto-review preview-only by default
[done] Keep dream as default Daily capability with gate/audit/undo
[done] Remove M10 knowledge-cache/wiki bridge/compact renderer runtime
[done] Remove top-level CLI import/purge and keep CLI as operator console
[done] Remove user-visible /hm:mark and /hm:prune artifact lifecycle commands
[done] Ensure MCP registry registers only public memory tools
[done] Add record payload boundary so split stores avoid LocalStructuredStore._blob_path
[P0 guard] Keep docs aligned with actual Done / Remaining / Removed status
[P1] Delete or move remaining Skill governance schema/serializer/store traces
[P1] Merge standalone metabolism/reflection naming into dream/background jobs
[P1] Refactor tools/session-distill into thin CLI plus lib modules
[P1] Delete session-distill KB/PRD and unused artifact lifecycle internals
[P1] Add/keep distill/review gate regression tests
[P2] Continue storage/search boundary split behind existing invariant tests
[P2] Freeze default read contract and delete untested advanced strategy branches
[P2] Keep native/Rust acceleration optional in public docs
```

---

## 11. 验收清单与证据索引

### Definition of Done

整体收敛不是一个提交结束的事项。当前状态按两层验收：

### 已满足的 public/default 边界

- 默认公开面只展示 local memory core loop。
- MCP 不要求用户选择 profile；public memory surface 不包含 auto apply、operator maintenance 或 Skill governance lifecycle tools。
- `/hm:distill` 默认 preview，不 confirm durable memory。
- `/hm:review` 是用户可理解、可审计的唯一持久化 gate。
- Daily slash 命令只剩 status/wake/search/search-all/distill/review/dream；mark/prune 用户入口已删除；KB/PRD 产品管理命令已删除。
- storage/search 已有一致性测试保护，并已启动 TruthStore/CandidateStore 边界拆分；拆出 store 不再访问 LocalStructuredStore._blob_path。
- storage/reflection job 通过 `DerivedIndex` public 边界复用 structured index，不再访问其它 store 的 private attribute。
- plugin 被表述为 integration bundle，不是 canonical API 或 Claude-only 产品。
- native/Rust 被表述为 optional acceleration，不污染 package version 叙事。
- standalone M07X metabolism/reflection 不出现在 README/quickstart、MCP/CLI/slash、status/doctor 或 maintenance read/debug 面；M10 knowledge-cache/wiki bridge 已删除，不作为仓库 runtime、产品或 maintenance 能力保留；dream 作为默认能力出现在 Daily 路径。
- 自动维护统一通过 dream 暴露；底层扫描/ledger 只作为 dream 内部实现细节，不形成独立 read/debug 产品面。
- Skill governance 不进入 MCP lifecycle tools、CLI 顶层命令或 Daily `/hm:*`；
  confirmed procedural memory 只作为 read hint 被使用。

### 剩余内部质量闭环

- `session-distill` 作为 P1 专项完成薄入口和 lib 拆分，但没有成为产品主轴。
- `session-distill` 有明确 readiness mapping、default summary contract 和外部同步策略。
- `harness_mem_export` 只能 suggest，不能 confirm/reject/replace/direct truth write。
- Skill governance 的 promotion/revision/deprecation schema、serializer、store 痕迹要么删除，要么迁出到独立 skill 专项。
- Dream / background job 内部命名不再让 metabolism/reflection 看起来像第二套产品面。
- read/context/signals 的高级策略默认不改变 wake/search 的稳定 contract；无测试、无 trace、无调用方的分支删除。
- `LocalStructuredStore` 继续降为兼容 facade，核心职责下沉到 TruthStore / CandidateStore / DerivedIndex / SearchFacade。

### 证据索引

以下路径/行号来自本次讨论中提供的本地证据，落 PR 前建议在本地重新 grep 与测试确认。

| 主题 | 证据/路径 |
|---|---|
| MCP 单公开面与工具面 | `harness_mem/mcp/tool_specs.py:PUBLIC_MCP_TOOL_NAMES`; `harness_mem/mcp/tool_registry.py:list_tools_result`; `harness_mem/mcp/executor.py:execute_tool_call`; `tests/test_mcp_public_surface_contract.py` |
| session-distill 薄入口 | `tools/session-distill/bin/session-distill.py`; `tools/session-distill/lib/cli.py`; `tools/session-distill/lib/cli_handlers/` |
| SourceAdapter 统一 | `tools/session-distill/lib/adapters/clients.py`; `tools/session-distill/lib/packet.py`; `tests/test_session_distill_adapters.py` |
| review gate 与 auto-review 冲突 | `plugins/harness-mem/commands/hm/daily/distill.md`; `tools/session-distill/SKILL.md`; `tests/test_mcp_public_surface_contract.py` |
| session-distill summary contract | `tools/session-distill/lib/summary.py`; `tests/test_session_distill_boundaries.py` |
| harness_mem_export suggest-only 边界 | `tools/session-distill/lib/harness_mem_export.py`; `tests/test_session_distill_boundaries.py` |
| 非 Daily slash command 清理与 raw cleanup guardrails | `harness_mem/integration/command_sync.py`; `tests/test_integration_command_sync.py`; `tools/session-distill/lib/cli.py`; `tests/test_session_distill_cli_guardrails.py` |
| storage/search 不变量 | `tests/test_storage_search_invariants.py` |
| storage truth/candidate 边界 | `harness_mem/storage/truth_store.py`; `harness_mem/storage/candidate_store.py`; `harness_mem/storage/local_structured_store.py` |
| storage derived index 边界 | `harness_mem/storage/derived_index.py`; `harness_mem/storage/local_structured_store.py:index`; `harness_mem/storage/local_verbatim_store.py:index`; `harness_mem/storage/reflection_job_store.py`; `harness_mem/storage/sqlite_index.py:locked_connection`; `tests/test_storage_search_invariants.py:test_reflection_jobs_use_public_derived_index_boundary` |
| SearchFacade 边界 | `harness_mem/search/backend.py:SearchFacade`; `tests/test_storage_search_invariants.py` |
| Skill governance 移除证据 | `tests/test_cli_surface.py`; `tests/test_mcp_public_surface_contract.py`; `harness_mem/mcp/tool_specs.py` |
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
6. dream 默认开启但必须 gate/audit/undo；standalone maintenance / governance / metabolism 产品面删除或移出主包。
```
