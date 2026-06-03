# Changelog

所有正式版本变更记录。格式参照 [Keep a Changelog](https://keepachangelog.com/)。

---

## [Unreleased]

---

## [2.9.57] — 2026-06-04

**主题：Generic MCP Empty-Packet S6 Evidence**

v2.9.57 收的是 `v2-user-test-packet` 的一条真实 coverage 扩展：generic MCP 现在不仅有
最小 read/write smoke、S8/S9 deeper workflow、fresh-home write-path smoke，还补上了
`S6 Empty evidence packet` 的 live stdio 证据。当前机器上，在 isolated temp home 下对一个
空项目直接调用 `prepare_session_distill(run_ingest=false)`，已经能稳定返回
`observation_count = 0`、零 status counters 和空 `observations` 包。这还不是 full matrix
闭环，但它确实把 packet 从“最小 smoke”往正式 scenario 覆盖推进了一步。

### Changed

- **packet S6 evidence**：`docs/v2-user-test-packet.md` 新增一条 `2026-06-04` generic MCP
  empty-packet entry，记录 live stdio `prepare_session_distill(run_ingest=false)` 的空包结果。
- **focused regression coverage**：新增
  `tests/test_v2_user_test_packet_empty_evidence_truth.py`，防止这条 S6 evidence 再次漂移消失。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.57`。

### Boundaries

- 本版本不宣称 full `12-scenario` cross-client matrix 已补齐。
- 它只新增了 generic MCP 在 `S6 Empty evidence packet` 这一条 scenario 上的 live evidence。

## [2.9.56] — 2026-06-04

**主题：Fresh-Home Write-Path Embedding Fail-Fast**

v2.9.56 收的是一个真实 runtime 缺口：在 fresh isolated home 下，generic MCP 的
`suggest_memory_entry` 仍可能因为 write-path embedding 触发首次 Hugging Face 模型下载而
卡住，导致交互式写入面超时。上一刀只给已经进入 `encode(...)` 的挂死加了超时熔断，但当前机器
上的 live stdio MCP 复跑表明，fresh-home 慢点更早出现在 cold-cache model load/download。
这一版把 write-path embedding 再收紧一层：如果本地没有缓存快照，就直接跳过 vec 写入并记
warning，而不是在候选写入这条交互路径上触发首次下载。

### Changed

- **cold-cache write-path skip**：`harness_mem.embedding.has_local_model_snapshot(...)`
  现在会先判断 embedding model 是否已在本地缓存；`persist_embedding(...)` 在 cold cache
  下直接跳过 vec 写入，不再触发首次下载。
- **existing timeout guard retained**：已有的 write-path timeout / circuit-breaker 仍保留，用于
  已缓存模型但 encode/import 挂住的另一类故障。
- **focused regression coverage**：`tests/test_disable_embeddings.py` 新增 cold-cache skip
  guard，防止 write path 再次在没有本地模型缓存时尝试 `get_model_loader(...)`。
- **packet/runtime evidence writeback**：`docs/v2-user-test-packet.md` 新增一条
  `2026-06-04` generic MCP fresh-home write-path smoke，证明不开
  `HARNESS_MEM_DISABLE_EMBEDDINGS` 时，isolated temp home 下的 real stdio
  `suggest_memory_entry` 已能快速返回。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.56`。

### Boundaries

- 本版本不宣称 full `12-scenario` cross-client matrix 已补齐。
- 它也不宣称 cold cache 下已经拿到了 vec row；当前保证的是交互式写路径不再被首次模型下载拖死。

## [2.9.55] — 2026-06-03

**主题：v2.2 Non-Claude Smoke Log Sync**

v2.9.55 收的是 `v2-user-test-packet` 的 non-Claude run-log 事实更新。上一版已经把 `v2.2`
从“完全闭环”收回成“runtime 已完成、手工 gate 未闭”，但 packet 本身仍写着
`Known gap: 非 Claude client ... 未跑`。当前机器上已经能跑通一条 Codex MCP 最小
smoke；继续补跑后，generic MCP raw JSON-RPC 最小 smoke 也已通过：`wake`、
`set_active_project`、`suggest_memory_entry`、`list_candidates` 都成功。这一版把这两条
non-Claude 证据补进 Run log，同时明确这还不等于 full matrix 已跑完。

### Changed

- **packet run-log truth sync**：`docs/v2-user-test-packet.md` 新增
  `2026-06-03` Codex MCP smoke entry 与 generic MCP JSON-RPC smoke entry，不再把
  non-Claude client 写成“完全未跑”。
- **status wording sync**：`docs/roadmap-v22x.md` 与 `docs/roadmap-status.md`
  现在明确：已有 Codex + generic MCP 两条 non-Claude smoke，但 full 12-scenario
  matrix 仍未闭环。
- **release writeback**：`docs/roadmap-v29.md`、版本号与本 changelog 已同步到 `2.9.55`。

### Boundaries

- 本版本不宣称 v2.2 full cross-client matrix 已完成。
- 它只把 packet / roadmap / status 回写到更精确的当前手工验证真值。

## [2.9.54] — 2026-06-03

**主题：v2.2 Manual Gate Truth Sync**

v2.9.54 收的是一个直接的完成性矛盾：`docs/roadmap-v22x.md` 和
`docs/roadmap-status.md` 还把 `v2.2` 写成“已完成”，但
`docs/v2-user-test-packet.md` 的 Run log 仍只有 Claude Code entry，并明确写着
`Known gap: 非 Claude client ... 未跑`。这一版不改 runtime，只把 `v2.2` 的状态收成
当前真值，并补 focused guard，防止以后再次把手工 gate 当成已经闭环。

### Changed

- **v2.2 status truth sync**：`docs/roadmap-v22x.md` 与 `docs/roadmap-status.md` 现在都明确区分：
  runtime / contract 已落地，但 `v2-user-test-packet` 要求的手工 non-Claude client
  Run log 仍未补齐。
- **focused regression coverage**：新增 `tests/test_v22_manual_gate_truth.py`。
- **release writeback**：`docs/roadmap-v29.md`、版本号与本 changelog 已同步到 `2.9.54`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或用户入口。
- 它只修正 `v2.2` 的完成性表述，使 roadmap / packet / automated evidence 重新一致。

## [2.9.53] — 2026-06-03

**主题：Reference Docs Truth Authority Sync**

v2.9.53 收的是三份高可见参考文档：`docs/cli/v2.4.md`、`docs/error-codes.md` 和
`docs/cli-design-expert.md`。此前它们会告诉维护者怎么操作、怎么看错误码、怎么评审 CLI 设计，
但没有直接说明当前 shipped 状态、已完成切片和未做边界应以 `roadmap-status.md` 与
`CHANGELOG.md` 为准。 这一版不改 runtime，只把这些参考文档接到统一 authority chain 上，
并补 focused guard。

### Changed

- **reference-doc authority sync**：`docs/cli/v2.4.md`、`docs/error-codes.md`、
  `docs/cli-design-expert.md` 现在都明确把当前发版状态、已完成切片和未做边界指向
  `roadmap-status.md` 与 `CHANGELOG.md`。
- **focused regression coverage**：新增 `tests/test_reference_docs_truth_authority_sync.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.53`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步高可见参考文档对当前 release truth authority 的说明。

## [2.9.52] — 2026-06-03

**主题：Usage Docs Truth Authority Sync**

v2.9.52 收的是两份高可见使用文档：`plugins/harness-mem/README.md` 和
`docs/best-practices.md`。此前它们会告诉用户怎么安装、怎么用，但没有直接说明当前 shipped
状态、已完成切片和未做边界应以 `roadmap-status.md` 与 `CHANGELOG.md` 为准。 这一版不改
runtime，只把这些使用文档接到同一条 authority chain 上，并补 focused guard。

### Changed

- **usage-doc authority sync**：`plugins/harness-mem/README.md` 与 `docs/best-practices.md`
  现在都明确把当前发版状态、已完成切片和未做边界指向 `roadmap-status.md` 与 `CHANGELOG.md`。
- **focused regression coverage**：新增 `tests/test_usage_docs_truth_authority_sync.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.52`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步高可见使用文档对当前 release truth authority 的说明。

## [2.9.51] — 2026-06-03

**主题：Docs README Truth Authority Sync**

v2.9.51 收的是 `docs/README.md` 对“当前发版真值看哪里”的 authority 说明。此前 docs 索引页
只列出了 `roadmap-status.md` 和各版本 roadmap，但没有像根入口与 `reference-projects.md` 那样
直接说明当前 shipped 状态、已完成切片和未做边界应以 `roadmap-status.md` 与 `CHANGELOG.md`
为准。 这一版不改 runtime，只把 docs 入口 authority chain 写清楚，并补 focused guard。

### Changed

- **docs README truth-authority sync**：`docs/README.md` 现在明确把当前发版状态、已完成切片和
  未做边界指向 `roadmap-status.md` 与 `CHANGELOG.md`。
- **focused regression coverage**：新增 `tests/test_docs_readme_truth_authority_sync.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.51`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 docs 文档索引入口对当前 release truth authority 的说明。

## [2.9.50] — 2026-06-03

**主题：Root Truth Authority Sync**

v2.9.50 收的是 repo 根 `README.md` 与 `AGENTS.md` 对“当前发版真值看哪里”的 authority 说明。
此前这两个高可见入口会把用户带到协作规则和能力说明，但没有直接指出当前 shipped 状态、
已完成切片和未做边界应以 `docs/roadmap-status.md` 与 `CHANGELOG.md` 为准。 这一版不改
runtime，只把根入口 authority chain 写清楚，并补 focused guard。

### Changed

- **root truth-authority sync**：`README.md` 与 `AGENTS.md` 现在都明确把当前发版状态、
  已完成切片和未做边界指向 `docs/roadmap-status.md` 与 `CHANGELOG.md`。
- **focused regression coverage**：新增 `tests/test_root_truth_authority_sync.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.50`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 repo 根入口对当前 release truth authority 的说明。

## [2.9.49] — 2026-06-03

**主题：Root README And AGENTS OpenSpec Layout Truth Sync**

v2.9.49 收的是 repo 根 `README.md` 和 `AGENTS.md` 对 OpenSpec 目录布局的说明。虽然
`docs/README.md` 已经收成三层结构，但根说明面仍把 OpenSpec 笼统写成一个 `openspec/`
目录桶。当前 repo 已没有 active change，高可见根说明面也应明确区分主 spec、active changes
和 archive。

### Changed

- **root OpenSpec layout sync**：`README.md` 与 `AGENTS.md` 现在明确区分
  `openspec/specs/`、`openspec/changes/` 和 `openspec/changes/archive/`。
- **focused regression coverage**：新增 `tests/test_repo_openspec_layout_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.49`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 repo 根说明面对 OpenSpec 层级的当前真值。

## [2.9.48] — 2026-06-03

**主题：User-Test-Packet OpenSpec Source Hierarchy Sync**

v2.9.48 收的是 `docs/v2-user-test-packet.md` 对 OpenSpec 真值入口层级的说明。当前 packet
仍把 `openspec/changes/<change>/specs/...` 写成普通落地路径之一，这会让维护者误以为 active
change spec 和主 `openspec/specs/...` 是并列默认入口。当前 repo 已没有 active change，因此
默认真值入口应先指向主 spec，只有确有 active change proposal 时才下钻到 change-local spec。

### Changed

- **user-test-packet source-hierarchy sync**：`docs/v2-user-test-packet.md` 现在明确默认先看
  `openspec/specs/...`，只有确有 active change proposal 时才下钻
  `openspec/changes/<change>/specs/...`。
- **focused regression coverage**：扩展 `tests/test_v2_user_test_packet_contract_source_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.48`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 `v2-user-test-packet` 对主 spec 与 active-change spec 的层级真值。

## [2.9.47] — 2026-06-03

**主题：Docs README OpenSpec Layout Truth Sync**

v2.9.47 收的是 `docs/README.md` 对 OpenSpec 目录布局的索引口径。当前索引页仍把设计规格
笼统写成在 `openspec/specs/` 和 `openspec/changes/`，但这会把主 spec、active changes
和 archive change 混成一个面。当前 repo 已没有 active change，这种说法不够精确。 这一版
不改 runtime，只把索引页收成当前主 spec / active change / archive 三层真值，并补 focused
guard。

### Changed

- **docs README OpenSpec layout sync**：`docs/README.md` 现在明确区分
  `openspec/specs/`、`openspec/changes/` 和 `openspec/changes/archive/` 的职责。
- **focused regression coverage**：新增 `tests/test_docs_readme_openspec_layout_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.47`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 `docs/README.md` 的 OpenSpec 索引真值，使主 spec、active changes 和 archive
  不再混成一个模糊目录面。

## [2.9.46] — 2026-06-03

**主题：Historical Roadmap And Skill Archive Pointer Truth Sync**

v2.9.46 收的是历史 roadmap 和 repo-local skill 里的 OpenSpec 指针真值。`docs/roadmap-v16x.md`、
`docs/roadmap-v17x.md`、`docs/roadmap-v23.md` 以及 `tools/session-distill/SKILL.md`
仍残留已归档切片的 active-change 路径，`session-distill` 还把当前主 spec 写成不存在的
`openspec/specs/memory-metabolism/spec.md`。这一版不改 runtime，只把这些高可见历史资料同步到
archive 真路径和当前主 spec。

### Changed

- **historical roadmap archive-pointer sync**：`docs/roadmap-v16x.md`、`docs/roadmap-v17x.md`、
  `docs/roadmap-v23.md` 里相关已完成切片现在统一回指 `openspec/changes/archive/...` 真路径。
- **session-distill metabolism-spec sync**：`tools/session-distill/SKILL.md` 现在回指已归档的
  `v230` design 和当前主 `openspec/specs/metabolism/spec.md`。
- **focused regression coverage**：新增 `tests/test_historical_archive_pointer_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.46`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步历史 roadmap / skill 对已归档 OpenSpec change 和当前主 spec 的指针真值。

## [2.9.45] — 2026-06-03

**主题：Roadmap-v27-v28 Archive Pointer Truth Sync**

v2.9.45 收的是 `docs/roadmap-v27.md` 与 `docs/roadmap-v28.md` 里已完成切片的 OpenSpec
指针口径。这两份 roadmap 仍把 `v270`–`v272` / `v280`–`v282` 写成
`openspec/changes/v27x...` / `v28x...`，看起来像还在 active change 目录里，但这些
变更实际上早已归档。 这一版不改 runtime，只把这些已完成条目回指 archive 真路径，并补
focused guard。

### Changed

- **roadmap-v27 archive-pointer sync**：`docs/roadmap-v27.md` 里 `v270`–`v272`
  的已完成条目现在统一回指 `openspec/changes/archive/...` 真路径。
- **roadmap-v28 archive-pointer sync**：`docs/roadmap-v28.md` 里 `v280`–`v282`
  的已完成条目现在统一回指 `openspec/changes/archive/...` 真路径。
- **focused regression coverage**：新增 `tests/test_roadmap_v27_v28_archive_pointer_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.45`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 `roadmap-v27` / `roadmap-v28` 对已归档 OpenSpec change 的指针真值。

## [2.9.44] — 2026-06-03

**主题：Roadmap-v29 Archive Pointer Truth Sync**

v2.9.44 收的是 `docs/roadmap-v29.md` 里最早一批已完成切片的 OpenSpec 指针口径。前半段
多个 `v290`–`v2912` 条目仍写成 `openspec/changes/v29xx...`，看起来像还在 active
change 目录里，但这些变更实际上早已归档。 这一版不改 runtime，只把这些已完成条目回指
archive 真路径，并补 focused guard。

### Changed

- **roadmap-v29 archive-pointer sync**：`docs/roadmap-v29.md` 里 `v290`–`v2912`
  的已完成条目现在统一回指 `openspec/changes/archive/...` 真路径。
- **focused regression coverage**：新增 `tests/test_roadmap_v29_archive_pointer_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.44`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 `roadmap-v29` 对已归档 OpenSpec change 的指针真值，避免完成条目继续伪装成 active change 路径。

## [2.9.43] — 2026-06-03

**主题：User-Test-Packet Contract Source Truth Sync**

v2.9.43 收的是 `docs/v2-user-test-packet.md` 的契约源与 Codex MCP 接入口径。当前 packet
仍引用已归档的 `openspec/changes/v220...` 路径，并写着“Codex CLI 当前版本所支持的
MCP 配置写法”，这两处都不是 repo 自己能稳定承诺的当前真值。 这一版不改 runtime，只
把 packet 回指主 spec，并把 Codex 接入说明收成 repo 自己维护并验证的 stdio 契约。

### Changed

- **user-test-packet contract-source sync**：`docs/v2-user-test-packet.md` 现在直接引用
  `openspec/specs/daily-workflow/spec.md` 作为契约真值源，不再指向 archived change 路径。
- **Codex MCP wording sync**：packet 里的 Codex 接入说明现在只描述 repo 当前维护并验证的
  stdio 契约，不再依赖“当前版本客户端支持写法”这种外部时态。
- **focused regression coverage**：新增 `tests/test_v2_user_test_packet_contract_source_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.43`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 `v2-user-test-packet` 的契约源与 Codex 接入口径，使之回到 repo 可验证的主 spec 真值。

## [2.9.42] — 2026-06-03

**主题：Roadmap-v29 Status Range Truth Sync**

v2.9.42 收的是 `docs/roadmap-v29.md` 顶部状态行的写法稳定性。上一版虽然把尾号推到
更近的 patch，但这条头部摘要仍是“逐 patch 枚举”的脆弱格式，每发一版就会再次立刻过时。
这一版不改 runtime，而是把头部状态收成跟当前版本真值对齐的范围式摘要，并让 focused
guard 跟随 `__version__` 校验。

### Changed

- **roadmap-v29 status range sync**：`docs/roadmap-v29.md` 顶部状态行现在写成
  `v2.9.0–v<current> 已完成` 这种范围式摘要，不再继续维护不断变长的 patch 枚举。
- **focused regression coverage**：`tests/test_roadmap_v29_status_tail_truth.py` 现在改成
  读取 `harness_mem.__version__` 校验头部状态范围。
- **release writeback**：`docs/roadmap-status.md`、版本号与本 changelog 已同步到
  `2.9.42`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只把 `roadmap-v29` 头部状态行从易漂移的逐 patch 枚举收束成稳定的范围式真值摘要。

## [2.9.41] — 2026-06-03

**主题：Roadmap-v29 Status Tail Truth Sync**

v2.9.41 收的是 `docs/roadmap-v29.md` 顶部状态行的尾号漂移。当前文档正文、版本真值和
`roadmap-status` 都已经推进到后续切片，但这条高可见头部摘要仍停在 `v2.9.39 已完成`。
这一版不改 runtime，只把状态行回写到当前真值，并补 focused guard。

### Changed

- **roadmap-v29 status tail sync**：`docs/roadmap-v29.md` 顶部状态行现在明确写到
  `v2.9.40 已完成`，不再把 release train 截在 `v2.9.39`。
- **focused regression coverage**：新增 `tests/test_roadmap_v29_status_tail_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、版本号与本 changelog 已同步到
  `2.9.41`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 `roadmap-v29` 顶部状态行的 release tail，并防止头部摘要再次停在更旧尾号。

## [2.9.40] — 2026-06-03

**主题：Best-Practices Wake Drilldown Truth Sync**

v2.9.40 收的是 `docs/best-practices.md` 里 wake 读面颗粒度的漂移。当前 shipped truth
已经把 MCP `wake(project_name=<project>)` 固定成默认 wake-up surface，但这份高可见
最佳实践文档的 runtime 工具表仍把 `get_task_handoffs` / `get_confirmed_rules` 摆成像是
默认起点。 这一版不改 runtime，只把工具表和 wake 小节回写到当前真值，并补 focused
guard。

### Changed

- **best-practices wake drilldown sync**：`docs/best-practices.md` 现在明确写成：
  `wake` 覆盖新 session 常见的 profile/rules/handoff 读取需求，而
  `get_task_handoffs` / `get_confirmed_rules` 只保留给显式 drilldown。
- **focused regression coverage**：新增 `tests/test_best_practices_wake_drilldown_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.40`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 `best-practices` 的 wake 读面颗粒度，并防止文档再次回流到把低层读工具写成默认 wake-up 起点的旧口径。

## [2.9.39] — 2026-06-03

**主题：Opt-In Hook Truth Sync**

v2.9.39 收的是根 README 和 AGENTS 里的 hook 能力口径漂移。当前 v2.4 已经交付
默认 `off` 的 opt-in host hook / scheduler trigger，但这两份高可见文档仍把
“没有 IDE hook”写成绝对句。 这一版不改 runtime，只把产品叙事回写到当前真值，并补
focused guard。

### Changed

- **README/AGENTS hook truth sync**：两份高可见文档现在都明确写成：
  没有默认自动随手记，但已存在默认 `off` 的 opt-in host hook / scheduler trigger。
- **focused regression coverage**：新增 `tests/test_opt_in_hook_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.39`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 README / AGENTS 的 hook 能力叙事，并防止它们再次回流到“没有 IDE hook”的绝对口径。

## [2.9.38] — 2026-06-03

**主题：Roadmap-Status Baseline Scope Sync**

v2.9.38 收的是 `docs/roadmap-status.md` 顶部 baseline 摘要的范围漂移。当前短结论和
版本索引都已经覆盖 `v1.5` 到 `v2.9`，但这段最高可见摘要仍只从 `v2.5` 起讲。 这一版
不改 runtime，只把 baseline 摘要回写到当前真值，并补 focused guard。

### Changed

- **roadmap-status baseline scope sync**：`docs/roadmap-status.md` 顶部 baseline
  摘要现在明确从 `v1.5` baseline 到 `v2.9` release train 总结已完成主线。
- **focused regression coverage**：`tests/test_roadmap_status_baseline_truth.py`
  现在也会拒绝回流到只从 `v2.5` 起讲的旧口径。
- **release writeback**：`docs/roadmap-v29.md`、版本号与本 changelog 已同步到 `2.9.38`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 `roadmap-status` 顶部 baseline 摘要范围，并防止该摘要再次回流到过窄的 `v2.5` 起点。

## [2.9.37] — 2026-06-03

**主题：Roadmap-Status Version Index Truth Sync**

v2.9.37 收的是 `docs/roadmap-status.md` 版本索引表的范围漂移。当前状态页、README 索引和
短结论都已经覆盖 `v1.5` 到 `v2.9`，但这张高可见索引表仍只从 `v2.2.x` 起列，而且节名
还保留“后续 Roadmap”的旧说法。 这一版不改 runtime，只把版本索引回写到当前真值，并补
focused guard。

### Changed

- **roadmap-status version-index sync**：`docs/roadmap-status.md` 的高可见版本索引
  现在从 `v1.5.x` 连续覆盖到 `v2.9.x`。
- **section label sync**：同一节标题现在改成 `版本索引`，不再写成会误导时间感的
  “后续 Roadmap”。
- **focused regression coverage**：新增 `tests/test_roadmap_status_version_index_truth.py`。
- **release writeback**：`docs/roadmap-v29.md`、版本号与本 changelog 已同步到 `2.9.37`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 `roadmap-status` 的版本索引范围与标题，并防止该索引再次回流到只从 `v2.2` 起列的旧口径。

## [2.9.36] — 2026-06-03

**主题：Roadmap-Status Short Summary Scope Sync**

v2.9.36 收的是 `docs/roadmap-status.md` 底部“短结论”的范围漂移。当前状态页与完成矩阵
已经覆盖 `v1.5` 到 `v2.9`，但这段高可见总结仍只从 `v2.2` 起讲。 这一版不改 runtime，
只把短结论回写到当前真值，并补 focused guard。

### Changed

- **roadmap-status short summary sync**：`docs/roadmap-status.md` 的“短结论”
  现在明确从 `v1.5` baseline 到 `v2.9` release train 总结已完成主线。
- **focused regression coverage**：`tests/test_roadmap_status_summary_truth.py`
  现在拒绝回流到只从 `v2.2` 起讲的旧口径。
- **release writeback**：`docs/roadmap-v29.md`、版本号与本 changelog 已同步到 `2.9.36`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 `roadmap-status` 的短结论范围，并防止该总结再次回流到过窄的 `v2.2` 起点。

## [2.9.35] — 2026-06-03

**主题：Docs README Status Range Truth Sync**

v2.9.35 收的是 `docs/README.md` 里 `roadmap-status.md` 索引说明的范围漂移。当前
完成矩阵已经明确包含 `v1.5.x`，但 docs index 仍把该状态页描述成“从 v1.6 到 v2.9”。
这一版不改 runtime，只把 docs index 回写到当前真值，并补 focused guard。

### Changed

- **docs README status-range sync**：`docs/README.md` 现在把 `roadmap-status.md`
  描述成覆盖 `v1.5` 到 `v2.9` 的已完成项、边界和未做项。
- **focused regression coverage**：新增 `tests/test_docs_readme_status_range_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.35`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 docs index 对 `roadmap-status.md` 的范围描述，并防止 README 再次回流到 `v1.6` 起算的旧口径。

## [2.9.34] — 2026-06-03

**主题：Roadmap-Status v2.9 Baseline Tail Sync**

v2.9.34 收的是 `docs/roadmap-status.md` 顶部“当前收口基线”摘要的尾号漂移。当前
`v2.9` 已连续发到 `2.9.33`，但这段高可见摘要仍把 release train 截在 `v2.9.27`。
这一版不改 runtime，只把顶层摘要回写到当前真值，并把 focused guard 改成跟随
`harness_mem.__version__` 校验。

### Changed

- **roadmap-status tail sync**：`docs/roadmap-status.md` 顶部摘要现在把 `v2.9`
  release train 明确写到当前版本尾号，不再停在 `v2.9.27`。
- **focused regression coverage**：`tests/test_roadmap_status_baseline_truth.py`
  现在改为跟随 `harness_mem.__version__` 校验，不再写死旧尾号。
- **release writeback**：`docs/roadmap-v29.md`、版本号与本 changelog 已同步到 `2.9.34`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 `roadmap-status` 顶部 baseline 摘要尾号，并防止该摘要再次回流到过时的 `v2.9.27`。

## [2.9.33] — 2026-06-03

**主题：Vision Authority Truth Sync**

v2.9.33 收的是 `docs/roadmap-vision-v16-v18.md` 与 `docs/reference-projects.md`
里的 authority 口径残留。相关 `v1.6` - `v1.8` 版本线早已完成，但这些文档还容易让人
把历史 vision 当成当前版本承诺依据。 这一版不改 runtime，只把 authority 写回当前真值，
并补 focused guard。

### Changed

- **vision header sync**：`docs/roadmap-vision-v16-v18.md` 头部状态现在明确写成
  历史远景文档（vision archive），并指向 `roadmap-status` / `CHANGELOG`。
- **reference authority sync**：`docs/reference-projects.md` 不再把 `roadmap-vision-v16-v18.md`
  写成当前路线承诺依据，而是把 `roadmap-status` / `CHANGELOG` 标成当前真值来源。
- **docs index sync**：`docs/README.md` 现在把 `roadmap-vision-v16-v18.md` 标成
  “历史远景方向，不等同于当前版本承诺路线图”。
- **focused regression coverage**：新增 `tests/test_vision_authority_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.33`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步历史 vision / reference 文档的 authority 口径，并防止这些文档回流到旧表述。

## [2.9.32] — 2026-06-03

**主题：Historical Draft Status Truth Sync**

v2.9.32 收的是 `docs/roadmap/dream-mechanism-absorption-v151-v17.md` 头部状态的残留旧口径。
相关 `v1.5.1` - `v1.7` 版本线早已完成，但这份历史设计稿仍只写着裸 `draft`，容易让人误以为
它还是当前活跃 roadmap。 这一版不改 runtime，只把历史草稿定位写回当前真值，并补 focused guard。

### Changed

- **historical draft header sync**：`docs/roadmap/dream-mechanism-absorption-v151-v17.md`
  头部状态现在明确写成历史设计稿（draft archive），并指向 `roadmap-status` /
  `CHANGELOG` 作为当前真值来源。
- **docs index sync**：`docs/README.md` 现在把 `docs/roadmap/` 标成历史 roadmap
  proposal / design drafts，而不是当前版本规划。
- **focused regression coverage**：新增 `tests/test_historical_draft_status_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.32`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步历史设计稿的状态口径，并防止该文档回流到裸 `draft` 的旧表述。

## [2.9.31] — 2026-06-03

**主题：Roadmap-v22x Status Truth Sync**

v2.9.31 收的是 `docs/roadmap-v22x.md` 头部状态的残留旧口径。当前 `v2.2` 早已完成，
但该历史 roadmap 头部仍写着“规划中”。这一版不改 runtime，只把该版本线文档写回
当前真值，并补 focused guard。

### Changed

- **roadmap-v22x header sync**：`docs/roadmap-v22x.md` 头部状态现在明确写成
  `v2.2.0 已完成`。
- **focused regression coverage**：新增 `tests/test_roadmap_v22x_status_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.31`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 `roadmap-v22x.md` 的版本线状态口径，并防止该历史 roadmap 回流到“规划中”的旧表述。

## [2.9.30] — 2026-06-03

**主题：Roadmap-v25 Status Truth Sync**

v2.9.30 收的是 `docs/roadmap-v25.md` 头部状态的残留旧口径。当前 `v2.5` 早已整体完成，
但文档头部仍写着“进行中”，`v2.5.2` 小节也还保留“待版本收口 / 发版”的历史说法。
这一版不改 runtime，只把该版本线文档写回当前真值，并补 focused guard。

### Changed

- **roadmap-v25 header sync**：`docs/roadmap-v25.md` 头部状态现在明确写成
  `v2.5.0 / v2.5.1 / v2.5.2 已完成`。
- **file-context section sync**：`v2.5.2` 小节现在明确写成已并入正式版本线，不再保留
  “待发版”口径。
- **focused regression coverage**：新增 `tests/test_roadmap_v25_status_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、`docs/roadmap-v29.md`、版本号与本
  changelog 已同步到 `2.9.30`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 roadmap slice。
- 它只同步 `roadmap-v25.md` 的版本线状态口径，并防止该历史 roadmap 回流到“进行中 / 待发版”的旧表述。

## [2.9.29] — 2026-06-03

**主题：Roadmap-Status Matrix Truth Sync**

v2.9.29 收的是 `docs/roadmap-status.md` 完成矩阵里的残留历史状态。当前矩阵里，
`v2.8.2` 和 `v2.9.8` 这类早已完成的历史切片仍被标成“当前收口基线”，但这只在它们各自
发版时成立，对当前 repo 真值已经过期。这一版不改 runtime，只把状态矩阵写回当前真值，
并补 focused guard。

### Changed

- **roadmap-status matrix sync**：`docs/roadmap-status.md` 里历史版本行不再保留
  “当前收口基线”状态，统一回写为 `已完成`。
- **focused regression coverage**：新增 `tests/test_roadmap_status_matrix_truth.py`。
- **release writeback**：`docs/roadmap-v29.md`、版本号与本 changelog 已同步到 `2.9.29`。

### Boundaries

- 本版本不新增新的 runtime 行为、maintenance command 或 roadmap slice。
- 它只同步 `roadmap-status` 的完成矩阵状态口径，并防止历史版本行再次回流到“当前收口基线”。

## [2.9.28] — 2026-06-03

**主题：Roadmap-Status Baseline Truth Sync**

v2.9.28 收的是 `docs/roadmap-status.md` 顶部“当前收口基线”摘要的残留旧口径。当前
shipped 版本线已经连续发到 `v2.9.27`，但那一段高可见摘要还只枚举到 `v2.9.11`。
这一版不改 runtime，只把顶部基线摘要写回当前真值，并补 focused guard。

### Changed

- **roadmap-status baseline sync**：`docs/roadmap-status.md` 顶部“当前收口基线”摘要
  现在明确把 `v2.9.0–v2.9.27` 视作同一条已完成的 release train。
- **focused regression coverage**：新增 `tests/test_roadmap_status_baseline_truth.py`。
- **release writeback**：`docs/roadmap-v29.md`、版本号与本 changelog 已同步到 `2.9.28`。

### Boundaries

- 本版本不新增新的 runtime 行为、maintenance command 或 roadmap slice。
- 它只同步 `roadmap-status` 顶部基线摘要到当前 shipped truth，并防止这段摘要回流到只写到 `v2.9.11` 的旧口径。

## [2.9.27] — 2026-06-03

**主题：Roadmap-v29 Theme Truth Sync**

v2.9.27 收的是 `docs/roadmap-v29.md` 顶部标题区的残留旧口径。虽然这条版本线在
正文里已经连续记录到了 `v2.9.26`，但文件头部仍把整个 `v2.9` 缩成单一
`PRD Sync Candidate Surface`。这一版不改 runtime，只把 roadmap 头部主题与目标摘要
写回当前真值，并补 focused guard。

### Changed

- **roadmap-v29 theme sync**：`docs/roadmap-v29.md` 顶部主题现在明确写成
  `PRD sync 起步，随后扩成 maintenance / triage / truth-sync release train`。
- **roadmap-v29 goal sync**：目标段现在明确区分：
  - `v2.9.0` 的起点是 `/hm:prd-sync`
  - `v2.9.1+` 继续扩成 status / doctor helper / collateral / truth-sync slices
- **focused regression coverage**：新增 `tests/test_roadmap_v29_theme_truth.py`。
- **release writeback**：`docs/roadmap-status.md`、版本号与本 changelog 已同步到 `2.9.27`。

### Boundaries

- 本版本不新增新的 runtime 行为、maintenance command 或 roadmap slice。
- 它只同步 `roadmap-v29.md` 顶部主题/目标摘要到当前 shipped truth，并防止文件头回流到过窄的旧单主题写法。

## [2.9.26] — 2026-06-03

**主题：Roadmap-Status Summary Truth Sync**

v2.9.26 收的是 `docs/roadmap-status.md` 底部短结论的残留旧口径。当前 shipped
版本线已经连续发到 `v2.9.26`，但总结段还停在“完成到 v2.8”。这一版不改 runtime，
只把高可见总结段写回当前真值，并补 focused guard。

### Changed

- **roadmap-status short-summary sync**：`docs/roadmap-status.md` 的短结论现在明确写出
  路线已连续收口到 `v2.9`，并点名 `v2.9` 已扩成 PRD sync / maintenance /
  triage / truth-sync release train。
- **focused regression coverage**：新增 `tests/test_roadmap_status_summary_truth.py`。
- **release writeback**：`docs/roadmap-v29.md`、版本号与本 changelog 已同步到 `2.9.26`。

### Boundaries

- 本版本不新增新的 runtime 行为、MCP tool、maintenance command 或 release slice。
- 它只同步 `roadmap-status` 的高可见总结段，并防止该总结回流到 “完成到 v2.8”
  的旧写法。

## [2.9.25] — 2026-06-03

**主题：v2.9 Index Truth Sync**

v2.9.25 收的是高可见文档索引里的版本线摘要漂移。`docs/README.md` 和
`docs/roadmap-status.md` 仍把整个 `v2.9` 缩成单一的 `PRD sync candidate surface`，
但当前 shipped 的 `v2.9` 早已从 `/hm:prd-sync` 起步，扩展成 maintenance、
triage 与 current-truth sync 的 release train。这一版不改 runtime，只把索引页写回
当前真值，并补 focused guard。

### Changed

- **docs index sync**：`docs/README.md` 现在把 `roadmap-v29.md` 描述为
  `PRD sync + maintenance/truth-sync release train`。
- **roadmap-status sync**：`docs/roadmap-status.md` 现在把 `v2.9.x` 摘要写成
  从 `/hm:prd-sync` 起步、随后扩成 maintenance / triage / truth-sync release train。
- **focused regression coverage**：新增 `tests/test_v29_index_truth.py`。
- **release writeback**：`docs/roadmap-v29.md`、版本号与本 changelog 已同步到 `2.9.25`。

### Boundaries

- 本版本不新增新的 MCP tool、maintenance command、PRD sync 行为或 truth-mutation 逻辑。
- 它只同步高可见索引页对 `v2.9` 版本线的摘要口径，并防止索引回流到过窄的旧说法。

## [2.9.24] — 2026-06-03

**主题：Roadmap-v22x Distill Truth Sync**

v2.9.24 收的是 `docs/roadmap-v22x.md` 里残留的一处 distill 主链旧口径。当前 shipped
runtime 里，distill 的 review 步骤已经是一等的 `auto_review_candidates(apply=true)`
surface；但 v2.2 roadmap 仍把闭环写成 `suggest_* -> list_candidates ->
auto-review/confirm/reject`。这一版不改 runtime，只把历史 roadmap 中仍会描述 active
contract 的这行写回当前 shipped truth，并补 focused guard。

### Changed

- **roadmap-v22x distill sync**：`docs/roadmap-v22x.md` 现在把 distill 闭环写成
  `prepare_session_distill -> session-distill -> suggest_* -> auto_review_candidates(apply=true) -> summary`。
- **focused regression coverage**：新增 `tests/test_roadmap_v22x_distill_truth.py`。
- **release/status writeback**：`docs/roadmap-v29.md` 与
  `docs/roadmap-status.md` 已同步到 v2.9.24。

### Boundaries

- 本版本不新增新的 auto-review policy、候选类型或 MCP runtime 行为。
- 它只同步历史 roadmap 中仍会描述 active distill contract 的表述，并防止该文档回流到旧主链写法。

## [2.9.23] — 2026-06-03

**主题：AGENTS Distill Truth Sync**

v2.9.23 收的是根 `AGENTS.md` 里残留的 distill 主链旧口径。当前 shipped runtime
里，distill 的 review 步骤已经是一等的
`auto_review_candidates(project_name=<project>, apply=true)` surface；但 `AGENTS.md`
仍把主链写成 `list_candidates` 加逐条 confirm/reject。这一版不改 runtime，只把
根事实文档写回当前 shipped review truth，并补 focused guard。

### Changed

- **AGENTS distill mainline sync**：`AGENTS.md` 现在把 distill 主链写成
  `prepare_session_distill -> suggest_* -> auto_review_candidates(project_name=<project>, apply=true)`。
- **repair boundary sync**：`list_candidates`、`confirm_*`、`reject_*` 现在明确只
  属于 repair/recheck drilldown，而不是默认 distill 主路径。
- **focused regression coverage**：新增 `tests/test_agents_distill_truth.py`。
- **release/status writeback**：`docs/roadmap-v29.md` 与
  `docs/roadmap-status.md` 已同步到 v2.9.23。

### Boundaries

- 本版本不新增新的 auto-review policy、候选类型或 MCP runtime 行为。
- 它只同步根 `AGENTS.md` 到当前 shipped distill review surface，并防止事实文档回流到旧主链写法。

## [2.9.22] — 2026-06-03

**主题：Session-Distill Skill Truth Sync**

v2.9.22 收的是 repo-local `session-distill` playbook 里残留的 distill review 旧口径。
当前 shipped runtime 里，distill 的 review 步骤已经是一等的
`auto_review_candidates(project_name=<project>, apply=true)` surface；但
`tools/session-distill/SKILL.md` 仍把主链写成 `list_candidates` 加逐条 confirm/reject，
plugin README 的 `/hm:distill` 摘要也还没有显式点名 `auto_review_candidates`。这一版
不改 runtime，只把这些高可见 repo-local playbook 写回当前 shipped review truth，
并补 focused guard。

### Changed

- **session-distill skill sync**：`tools/session-distill/SKILL.md` 现在把
  `auto_review_candidates(project_name=<project>, apply=true)` 写成 default review
  surface。
- **drilldown boundary sync**：`list_candidates`、`confirm_*`、`reject_*` 现在明确只
  属于显式 drilldown / user-correction / repair 流，而不是默认 distill 主链。
- **plugin distill summary sync**：`plugins/harness-mem/README.md` 的 `/hm:distill`
  摘要现在直接提到 `auto_review_candidates`。
- **focused regression coverage**：新增 `tests/test_session_distill_skill_truth.py`。
- **release/status writeback**：`docs/roadmap-v29.md` 与
  `docs/roadmap-status.md` 已同步到 v2.9.22。

### Boundaries

- 本版本不新增新的 auto-review policy、候选类型或 MCP runtime 行为。
- 它只同步 repo-local distill playbook 到当前 shipped review surface，并防止 playbook 回流到旧主链写法。

## [2.9.21] — 2026-06-03

**主题：V2 User Test Packet Distill Truth Sync**

v2.9.21 收的是 `docs/v2-user-test-packet.md` 里残留的一处 generic MCP distill
旧口径。当前 shipped runtime 里，distill 的 review 步骤已经是一等的
`auto_review_candidates` surface；但 v2 user test packet 仍把 generic MCP 主链写成
`prepare_session_distill -> suggest_* -> list_candidates -> auto_review_candidates`。
这一版不改 runtime，只把 packet 写回当前 shipped review truth，并补 focused
guard。

### Changed

- **v2 user test packet sync**：`docs/v2-user-test-packet.md` 的 generic MCP distill
  链现在直接写成 `prepare_session_distill -> suggest_* -> auto_review_candidates`。
- **focused regression coverage**：新增 `tests/test_v2_user_test_packet_distill_truth.py`。
- **release/status writeback**：`docs/roadmap-v29.md` 与
  `docs/roadmap-status.md` 已同步到 v2.9.21。

### Boundaries

- 本版本不新增新的 auto-review policy、候选类型或 MCP runtime 行为。
- 它只同步 v2 user test packet 的 generic MCP distill 主链，并防止 packet 回流到旧测试链路写法。

## [2.9.20] — 2026-06-03

**主题：README Distill Workflow Truth Sync**

v2.9.20 收的是 `README.md` 里残留的一处 distill workflow 旧口径。当前 shipped
runtime 里，distill 的 review 步骤已经是一等的
`auto_review_candidates(project_name=<project>, apply=true)` surface；但 README 的
Workflow Skill Boundary 图还在画 `list_candidates -> auto-review / confirm / reject`
这条更早的主链。这一版不改 runtime，只把 README 图写回当前 shipped review truth，
并补 focused guard。

### Changed

- **README workflow sync**：Workflow Skill Boundary 图现在把 distill review 步骤
  直接写成 `auto_review_candidates(apply=true)`。
- **focused regression coverage**：新增 `tests/test_readme_distill_truth.py`。
- **release/status writeback**：`docs/roadmap-v29.md` 与
  `docs/roadmap-status.md` 已同步到 v2.9.20。

### Boundaries

- 本版本不新增新的 auto-review policy、候选类型或 MCP runtime 行为。
- 它只同步 README 的 distill workflow 图到当前 shipped review surface，并防止 README 回流到旧主链画法。

## [2.9.19] — 2026-06-03

**主题：Best-Practices Auto-Review Truth Sync**

v2.9.19 收的是 `docs/best-practices.md` 里残留的 auto-review 旧口径。当前
shipped runtime 里，distill 的低风险 review 已经是一等的
`auto_review_candidates(project_name=<project>, apply=true)` shared surface；但
`best-practices` 的角色表、候选层说明和管理工具表里还把 `list_candidates` +
`confirm_*` / `reject_*` 写成默认 distill 路径。这一版不改 runtime，只把
`best-practices` 写回当前 shipped review truth，并补 focused guard。

### Changed

- **best-practices role sync**：`Memory Expert` 现在明确默认复用
  `auto_review_candidates`，必要时再查看 `applied_decisions`。
- **candidate-loop guidance sync**：`Gardener` 行为现在明确在 `/hm:distill`
  同一轮调用 `auto_review_candidates(project_name=<project>, apply=true)`。
- **tool catalog sync**：管理工具表现在把 `auto_review_candidates` 记为默认
  distill/review surface；`list_candidates` 降为显式 drilldown/recheck 工具。
- **focused regression coverage**：新增 `tests/test_best_practices_auto_review_truth.py`。
- **release/status writeback**：`docs/roadmap-v29.md` 与
  `docs/roadmap-status.md` 已同步到 v2.9.19。

### Boundaries

- 本版本不新增新的 auto-review policy、候选类型或 MCP runtime 行为。
- 它只同步 `best-practices` 文档到当前 shipped distill review surface，并防止文档回流到 per-item review 的旧写法。

## [2.9.18] — 2026-06-03

**主题：Status Entrypoint Truth Sync**

v2.9.18 收的是 `/hm:status` 用户面真路径的残余漂移。当前 shipped runtime 里，
status triage 已经有一等的 MCP `get_project_status(project_name=<project>)`
surface，会直接返回 `phase`、`suggested_slash`、`reason` 和可选 repair hint；但
repo-local `/hm:status` 命令文档还在教 agent 额外拼 `get_project_profile`、
`list_candidates` 和 `timeline`，MCP 主 spec 的 status 示例也还没把 triage 字段写全。
这一版不改 runtime，只把这些高可见入口同步回当前 shipped status truth，并补 focused
guard。

### Changed

- **`/hm:status` command truth sync**：`plugins/harness-mem/commands/hm/status.md`
  现在把 `get_project_status(project_name=<project>)` 写成默认 triage surface，并把
  `timeline` / `list_candidates` 下放为用户显式追问时的 drilldown。
- **status example sync**：`openspec/specs/mcp/spec.md` 的 status 示例现在直接展示
  `phase`、`suggested_slash`、`reason`、`repair_hint` 和 `repair_reason`。
- **workflow spec sync**：`openspec/specs/daily-workflow/spec.md` 新增 `/hm:status`
  guidance requirement，防止文档再回流到手工拼低层读工具的旧路径。
- **focused regression coverage**：新增 `tests/test_status_entrypoint_truth.py`。
- **release/status writeback**：`docs/roadmap-v29.md` 与
  `docs/roadmap-status.md` 已同步到 v2.9.18。

### Boundaries

- 本版本不新增新的 status runtime 字段、triage policy 或 MCP 行为。
- 它只同步 `/hm:status` 用户面真路径，并防止文档/spec 回流到手工 assembly 的旧写法。

## [2.9.17] — 2026-06-03

**主题：Distill Auto-Review Entrypoint Truth Sync**

v2.9.17 收的是 `/hm:distill` 用户面真路径的残余漂移。当前 shipped runtime 里，
distill 的低风险 review 已经有共享的 MCP `auto_review_candidates(apply=true)`
surface；但 repo-local `/hm:distill` 文档、`harness-mem` skill 和 MCP 主 spec 示例
里还保留着“先 `list_candidates` 再逐条 `confirm_*` / `reject_*`”的旧写法。这一版
不改 runtime，只把这些高可见入口同步回当前 shipped review truth，并补 focused
guard。

### Changed

- **`/hm:distill` command truth sync**：`plugins/harness-mem/commands/hm/distill.md`
  现在把 `auto_review_candidates(project_name=<project>, apply=true)` 写成默认
  review surface，并要求最终摘要以 canonical counters 和 `applied_decisions`
  为准。
- **repo-local skill sync**：`plugins/harness-mem/skills/harness-mem/SKILL.md`
  不再保留 “when available” 式旧回退；默认 distill review 路径已经明确收束到
  `auto_review_candidates(...)`。
- **MCP example sync**：`openspec/specs/mcp/spec.md` 的 distill closed-loop 示例
  现在直接展示 `auto_review_candidates` 返回的 summary 和 `applied_decisions`。
- **focused regression coverage**：新增 `tests/test_distill_auto_review_truth.py`。
- **release/status writeback**：`docs/roadmap-v29.md` 与
  `docs/roadmap-status.md` 已同步到 v2.9.17。

### Boundaries

- 本版本不新增新的 auto-review policy、候选类型或 MCP runtime 行为。
- 它只同步用户面 distill 真路径，并防止文档/skill 回流到手工 per-item review 的旧写法。

## [2.9.16] — 2026-06-03

**主题：Best-Practices Wake Truth Sync**

v2.9.16 收的是 `docs/best-practices.md` 对 wake surface 的残余抽象写法。当前
shipped runtime 里，`wake` 已经是一等 MCP read surface，并且 compact renderer
与 skill hints 都挂在它上面；但最佳实践文档的 runtime 工具表还没把 `wake`
列为一等读取工具，wake-up 小节也还停留在“调用 wake 逻辑”的旧表述。这一版不改
runtime，只把 best-practices 写回到当前 shipped truth，并补 focused guard。

### Changed

- **best-practices tool catalog sync**：`docs/best-practices.md` 现在把 `wake`
  列为一等读取工具。
- **best-practices wake guidance sync**：wake-up 小节现在明确默认走
  MCP `wake(project_name=<project>)`，并把 `renderer="compact"` /
  `include_skill_hints=true` 收成显式 opt-in。
- **focused regression coverage**：新增 `tests/test_best_practices_wake_truth.py`。
- **release/status writeback**：`docs/roadmap-v29.md` 与
  `docs/roadmap-status.md` 已同步到 v2.9.16。

### Boundaries

- 本版本不新增新的 wake runtime 行为。
- 它只同步 `best-practices` 文档到当前 shipped wake surface。

## [2.9.15] — 2026-06-03

**主题：Wake Entrypoint Truth Sync**

v2.9.15 收的是 repo-local plugin 和 skill 里的 `/hm:wake` 旧 choreography。
当前 shipped runtime 早已有一等 MCP `wake` surface，并且 v2.5/v2.6/v2.7 把
renderer、compact generated summary、skill hints 都挂在这条面上；但
`plugins/harness-mem/commands/hm/wake.md` 和 repo-local `harness-mem` skill
还在教 agent 手工拼 `get_project_profile` / `get_task_handoffs` /
`get_confirmed_rules` / `timeline`。这一版不改 runtime，只把用户真路径收回到
shipped MCP `wake` contract，并加 focused guard 锁住。

### Changed

- **`/hm:wake` command truth sync**：`plugins/harness-mem/commands/hm/wake.md`
  现在以 MCP `wake(project_name=<project>)` 为默认路径，并补上
  `renderer="compact"` / `include_skill_hints=true` 的 opt-in 说明。
- **repo-local skill wake guidance sync**：
  `plugins/harness-mem/skills/harness-mem/SKILL.md` 的 status/wake 流程现在以
  `get_project_status` + `wake(...)` 为主，不再默认手工拼低层读工具。
- **focused regression coverage**：新增 `tests/test_wake_entrypoint_truth.py`，
  防止 `/hm:wake` 文档和 skill 指引回流到旧 choreography。
- **release/status writeback**：`docs/roadmap-v29.md` 与
  `docs/roadmap-status.md` 已同步到 v2.9.15。

### Boundaries

- 本版本不新增新的 wake renderer、skill-hint 语义或底层 MCP 工具。
- 它只同步 repo-local command/skill 文档到 shipped MCP `wake` surface。

## [2.9.14] — 2026-06-03

**主题：v2.4 Config And Job Truth Sync**

v2.9.14 收的是 `roadmap-v24` 里两处同主题的规划态残留。当前 shipped v2.4
runtime 的 merged-config loader 只认四个 key：
`triggers.after_agent`、`triggers.scheduler`、`distill.mode`、`worker.mode`；
它不会解析 `project_name`，也不会读取 `active_project.txt`。同时，当前 queue
model 只有一个 `ReflectionJob` schema，`review` 只是它的 phase，不存在单独的
`ReviewJob` 类型。这一版不改 runtime，只把文档、主 spec 和 focused guard
收回到这份 current truth。

### Changed

- **v2.4 roadmap config truth sync**：`docs/roadmap-v24.md` 不再把
  `.harness-mem.toml` 写成会覆盖 `project_name`，也不再把
  `active_project.txt` 写进 `load_merged_config(project_root)` contract。
- **v2.4 roadmap job-model truth sync**：`docs/roadmap-v24.md` 现在明确只有
  `ReflectionJob` schema；`review` 只是 phase，不是单独 job 类型。
- **focused regression coverage**：新增 `tests/test_v24_config_and_job_truth.py`，
  把 config-loader scope 和 single-ReflectionJob model 锁到当前 runtime truth。
- **release/status writeback**：`docs/roadmap-v29.md` 与
  `docs/roadmap-status.md` 已同步到 v2.9.14。

### Boundaries

- 本版本不新增 config key、project-name resolver、queue schema 或新的 review job。
- 它只同步 v2.4 current-truth 文档，并防止规划态表述再次回流。

## [2.9.13] — 2026-06-03

**主题：Host-Entry Module Truth Sync**

v2.9.13 收的是一处剩余的 v2.4 host-trigger 文档漂移。当前 runtime、hook 模板、
CLI operator doc 和 tests 都已经统一到 `python -m harness_mem.host_entry` 的
flag-only 调用形式，但 `roadmap-v24` 还留着 `harness_mem.<host_entry>` 占位符、
`python -m harness_mem.host` 旧模块名，以及把 `reflection_once` 写成 host-entry
位置参数的旧例子。这一版不改 runtime，只把当前文档真值收回到 shipped host-entry
contract，并用 focused guard 锁住。

### Changed

- **v2.4 roadmap host-entry sync**：`docs/roadmap-v24.md` 现在统一使用
  `python -m harness_mem.host_entry --project-root ... --source ide_hook ...`
  的 shipped invocation 形式。
- **focused regression coverage**：新增 `tests/test_host_entry_module_truth.py`，
  防止 current-truth docs 回流到 `harness_mem.<host_entry>`、
  `python -m harness_mem.host` 或 `host_entry reflection_once` 旧口径。
- **release/status writeback**：`docs/roadmap-v29.md` 与
  `docs/roadmap-status.md` 已同步到 v2.9.13。

### Boundaries

- 本版本不新增 host-entry flags、CLI 命令、hook 行为或 reflection runtime。
- 它只同步当前文档真值，并防止旧的 host-entry 调用示例继续误导维护者。

## [2.9.12] — 2026-06-03

**主题：Distill-Mode Truth Sync**

v2.9.12 继续收 v2.4 配置口径。当前 runtime 和 tests 一直只承认
`distill.mode = "defer_to_agent" | "inline" | "worker"`，但 `roadmap-v24`
里还留着 `notify_only` / `embedded_llm` 这组更早的设计值。这一版不改行为，只把
current-truth 文档收回到 shipped loader truth，并把 focused guard 扩到
`distill.mode`。

### Changed

- **v2.4 roadmap truth sync**：`docs/roadmap-v24.md` 现在把 `distill.mode` 表收成
  `defer_to_agent` / `inline` / `worker`。
- **status/release sync**：`docs/roadmap-status.md` 与 `docs/roadmap-v29.md` 已同步到
  v2.9.12。
- **focused regression coverage**：`tests/test_worker_mode_truth.py` 现在也守
  `distill.mode` 的文档口径。

### Boundaries

- 本版本不新增 inline LLM orchestration、worker daemon、notify-only channel 或 host-entry 行为。
- 它只同步当前 config truth，并防止旧的 `notify_only` / `embedded_llm` 口径继续误导用户。

## [2.9.11] — 2026-06-03

**主题：Scheduler Trigger Truth Sync**

v2.9.11 继续收 v2.4 配置口径。当前 runtime 和 tests 一直只承认
`triggers.scheduler = "off" | "on"`，但 `roadmap-v24` 仍把它写成
`off|cron`。这一版不改行为，只把剩余 current-truth 文档收回到 shipped loader
truth，并把 focused guard 扩到 scheduler trigger。

### Changed

- **v2.4 roadmap truth sync**：`docs/roadmap-v24.md` 现在把
  `triggers.scheduler` 写成 `off|on` scheduler gate，而不是 `off|cron`。
- **operator doc clarification**：`docs/cli/v2.4.md` 现在明确 `on` 只是
  scheduler/cron host trigger gate，不代表当前 runtime 自带 schedule installer。
- **status/release writeback**：`docs/roadmap-status.md` 与 `docs/roadmap-v29.md`
  已同步到 v2.9.11。
- **focused regression coverage**：`tests/test_worker_mode_truth.py` 现在也守
  `triggers.scheduler` 的文档口径。

### Boundaries

- 本版本不新增 scheduler、cron expression parser、daemon 或 host-entry 行为。
- 它只同步当前 config truth，并防止 `triggers.scheduler=cron` 旧说法继续误导用户。

## [2.9.10] — 2026-06-03

**主题：Worker-Mode Truth Sync**

v2.9.10 收的是一个 current-truth 配置口径修正。当前 runtime 和 tests 一直只承认
`worker.mode = "off" | "on"`，但少数 v2.4 路线文档仍把它写成
`worker.mode = "daemon"`。这一版不改行为，只把这些高可见文档收回到 shipped
loader truth，并加 focused guard 防止旧口径回流。

### Changed

- **v2.4 roadmap truth sync**：`docs/roadmap-v24.md` 现在把 `worker.mode` 写成
  `off|on` non-default gate，而不是 `off|daemon`。
- **status truth sync**：`docs/roadmap-status.md` 不再把未完成项写成
  `worker.mode=daemon`；改为明确当前只有 `off/on` gate，且无默认后台安装器。
- **operator doc clarification**：`docs/cli/v2.4.md` 现在明确 `on` 只是 config
  gate，不代表 shipped always-on daemon installer。
- **focused regression coverage**：新增 `tests/test_worker_mode_truth.py`，把文档口径
  绑定到 `_RECOGNIZED_KEYS` 的当前 runtime truth。

### Boundaries

- 本版本不新增 daemon、worker、scheduler 或 host-entry 运行时行为。
- 它只同步当前 config truth，并防止 `worker.mode=daemon` 旧说法继续误导用户。

## [2.9.9] — 2026-06-02

**主题：Reflection Project-Root Resolution**

v2.9.9 收的是一个小但真实的运行时缺口。共享 reflection business command
`reflection_once(...)` 在 `project_root` 缺省时，之前会直接把调用方 cwd 记进
job，即使 commands layer 已经可以按 `project_name` 找到已知 repo root。
这一版把解析顺序收紧成“先 known root，后 cwd”，并补 focused tests 锁住它。

### Changed

- **known-root-first resolution**：`reflection_once(...)` 现在在
  `project_root=None` 时优先调用 commands-layer 的 `find_project_root(project_name)`。
- **cwd final fallback**：只有在没有已知 project root 时，才回退到当前工作目录。
- **focused regression coverage**：`tests/test_reflection_once_integration.py`
  新增 known-root path 与 cwd fallback 两个覆盖。

### Boundaries

- 本版本不引入新的 reflection queue、daemon、worker 或 CLI surface。
- `host_entry` 仍然优先传显式 `--project-root`；这次只收紧共享 business command 的缺省解析语义。

## [2.9.8] — 2026-06-02

**主题：Maintenance Surface Collateral Guard**

v2.9.8 不再继续靠人工扫文档来守 maintenance-surface 真值，而是给已经同步好的
README、MCP spec、telemetry spec 和 v2 user-test packet 加上 focused
regression guard。这样后续如果谁把 `config` / `integration` 从这些高可见摘要里
删掉，测试会直接报警。

### Added

- **collateral truth guard**：新增 `tests/test_maintenance_surface_collateral.py`，
  覆盖 README、`openspec/specs/mcp/spec.md`、
  `openspec/specs/telemetry/spec.md`、`docs/v2-user-test-packet.md` 的当前
  maintenance-surface 摘要。

### Boundaries

- 本版本不新增 CLI、MCP、telemetry 或 plugin 运行时能力。
- 它只给既有 collateral truth 增加 focused regression guard。

## [2.9.7] — 2026-06-02

**主题：README And Telemetry Maintenance Truth**

v2.9.7 收的是剩余两处高可见 maintenance-surface 旧口径：README 的架构图摘要和
telemetry 主 spec。两者都还停留在 `config` / `integration` 发版之前的命令集。
这一版不改 runtime，只把这些 collateral 以及 `roadmap-status` 里的重复段同步到
当前真值。

### Changed

- **README maintenance summary sync**：README 架构图中的 CLI maintenance console
  现在包含 `config` / `integration`。
- **telemetry spec sync**：`openspec/specs/telemetry/spec.md` 现在把
  `qs` / `config` / `integration` 视为当前维护 CLI 覆盖的一部分。
- **status doc cleanup**：移除了 `docs/roadmap-status.md` 中重复的一行
  v2.9 summary。

### Boundaries

- 本版本不新增 CLI、MCP、telemetry 运行时能力。
- 它只修 README / telemetry spec / status doc 的 current-truth 漂移。

## [2.9.6] — 2026-06-02

**主题：Maintenance Surface Collateral Sync**

v2.9.6 收的是两处残余的 maintenance-surface 旧口径。虽然主 CLI spec、stale
doc guard、shell completion 都已经同步到 `config` / `integration` 时代，
`openspec/specs/mcp/spec.md` 和 `docs/v2-user-test-packet.md` 仍然停留在更早的
维护命令集。这个版本不改 runtime，只把剩余高可见 collateral 收回到同一份真值。

### Changed

- **MCP spec sync**：`openspec/specs/mcp/spec.md` 现在把 CLI 维护面写为
  `init / quickstart / qs / doctor / import / purge / maintenance / config / integration`。
- **user-test packet sync**：`docs/v2-user-test-packet.md` 现在把
  `config` / `integration` 视为允许的维护类 CLI 命令。
- **release writeback**：`docs/roadmap-v29.md` 与 `docs/roadmap-status.md`
  已同步到 v2.9.6。

### Boundaries

- 本版本不新增 CLI、MCP、plugin 或 slash 运行时能力。
- 它只修剩余 spec / user-test collateral 的 current-truth 漂移。

## [2.9.5] — 2026-06-02

**主题：Shell Completion Maintenance Truth**

v2.9.5 修复的是 CLI completion surface 的最后一处旧口径。虽然 `harness-mem --help`
和主 CLI spec 早已升级到 `config` / `integration` maintenance namespaces，
`harness_mem.shell_completion` 生成的 bash / zsh / fish 脚本仍然停留在更早的命令集，
甚至 zsh 连 `qs` alias 都没带上。这个版本把 completion surface 收回到当前真值，
并用 focused tests 把它锁住。

### Changed

- **top-level completion sync**：bash / zsh / fish completion 现在都包含
  `config` / `integration` / `qs`。
- **namespace action completion**：completion 现在会补出 `config get/set/list/validate`
  和 `integration install-cursor-hook/install-claude-hook`。
- **focused regression coverage**：新增 `tests/test_shell_completion.py`，
  同时覆盖生成器输出和 CLI `--completion` 路径。

### Boundaries

- 本版本不新增新的 CLI 命令或 MCP 能力。
- 它只把现有 `--completion` surface 对齐到已经 shipped 的 maintenance console。

## [2.9.4] — 2026-06-02

**主题：Stale CLI Surface Guard Sync**

v2.9.4 收的是一个 guardrail current-truth 偏差。v2.9.3 已把主 CLI spec 同步到
真实 `harness-mem --help`，明确 top-level maintenance surface 包含 `config` 和
`integration`；但 focused regression test `tests/test_stale_cli_surface.py` 的注释与
maintenance allowlist 还停留在更早的口径。这个版本不改运行时，只把 stale-surface
守护测试和发版文档同步到当前真值。

### Changed

- **stale-surface guard sync**：`tests/test_stale_cli_surface.py` 现在把当前
  maintenance-only CLI surface 记为 `init / quickstart / qs / doctor / import /
  purge / maintenance / config / integration`。
- **maintenance allowlist sync**：focused doc guard 现在把 `config` 和
  `integration` 视为受支持的 maintenance verbs，而不是未来文档补写时的假阳性来源。
- **release writeback**：`docs/roadmap-v29.md` 与 `docs/roadmap-status.md`
  已同步到 v2.9.4。

### Boundaries

- 本版本不新增 CLI 或 MCP 运行时能力。
- 该守护测试继续只禁止被移除的 daily-memory CLI verbs：
  `wake/search/timeline/candidates/distill`。
## [2.9.3] — 2026-06-02

**主题：CLI Maintenance Surface Truth**

v2.9.3 收的是一处 current-truth 偏差：真实 `harness-mem --help` 早已把
`config` 和 `integration` 暴露为 top-level maintenance commands，测试也一直按
这个表面验证；但主 `openspec/specs/cli/spec.md` 还停留在只到 `maintenance`
为止。这个版本不新增运行时能力，只把主 contract、roadmap 和发版元数据对齐到
已经 shipped 的 CLI maintenance surface。

### Changed

- **top-level CLI contract sync**：主 `cli` spec 现在把当前 maintenance command
  set 记为 `init / quickstart / qs / doctor / import / purge / maintenance /
  config / integration`，与真实 `harness-mem --help` 一致。
- **explicit config namespace contract**：主 `cli` spec 现在明确 `config
  get/set/list/validate` 属于 TOML 配置维护命名空间，而不是日常 memory
  workflow surface。
- **explicit integration namespace contract**：主 `cli` spec 现在明确
  `integration install-cursor-hook/install-claude-hook` 属于 host-entry hook
  安装命名空间，不会重新引入业务型 CLI 子命令。
- **release writeback**：`docs/roadmap-v29.md` 与
  `docs/roadmap-status.md` 已同步到 v2.9.3。

### Boundaries

- 本版本不新增 CLI 业务子命令。
- `wake`、`search`、`distill`、`ingest`、`reflection` 等日常 memory flows
  仍然不属于 top-level CLI surface。

## [2.9.2] — 2026-06-02

**主题：Plugin Doctor Helper Integrity**

v2.9.2 修复了 repo-local plugin 的 `doctor.ps1` helper。此前脚本先跑
`harness-mem doctor`，然后又调用已经被明确移除的 CLI `status` 子命令，导致用户
在看到正确的 doctor 输出后仍然以 `invalid choice: 'status'` 失败收尾。现在该
helper 被收回到维护控制台的真实边界内：只调用受支持的 maintenance 命令，`-Wake`
也只作为 IDE-native wake 提示，而不是重新引入 CLI `status/wake` 面。

### Fixed

- **doctor helper no longer calls removed CLI status**：`plugins/harness-mem/scripts/doctor.ps1`
  现在只运行 `python -m harness_mem.cli doctor`。
- **hint-only `-Wake`**：当传入 `-Wake` 时，脚本会在 doctor 完成后输出
  `/hm:wake` / 自然语言 wake 提示，而不是调用不存在的 CLI 子命令。
- **script smoke coverage**：新增隔离 `HOME/USERPROFILE` 的脚本 smoke，
  证明 helper 成功返回且不再输出 `invalid choice: 'status'`。

### Boundaries

- 该 helper 仍然是 repo-local plugin 的本地验证脚本，不是日常 memory CLI surface。
- 它不会重新暴露 CLI `status` 或 `wake` 子命令。

## [2.9.1] — 2026-06-02

**主题：Status Triage Surface**

v2.9.1 把已经广泛出现在 README、plugin 安装输出和 slash 命令里的 `/hm:status`
收束成了正式的 read-only triage surface。此前 repo 存在口径分裂：有的文档把它说成
`doctor` 代理，有的命令说明又把它当成 MCP `get_project_status` 驱动的状态入口。
现在这条线被正式锁定：`/hm:status` 是一个 slash-first 的项目记忆分诊入口，MCP
会直接返回下一步 hint，而不是让各处 prompt 自己猜。

### Added

- **v2.9.1 status triage contract**：`/hm:status` 正式进入 daily-workflow
  contract，成为 read-only 项目状态入口。
- **structured MCP hints**：`get_project_status` 现在会返回 `phase`、
  `suggested_slash`、`reason`，并在存在 pending candidates 时追加
  `repair_hint` / `repair_reason`。
- **review-only boundary**：pending candidates 不会让 `/hm:review` 升格成
  主 happy-path；它只作为显式 repair hint 暴露。
- **focused regression coverage**：新增 ready / empty / pending-candidate
  三种 `get_project_status` triage 场景测试。

### Boundaries

- `/hm:status` 仍是只读入口，不写候选、不改 truth。
- 主 happy path 仍然是 empty → `/hm:distill`、ready → `/hm:wake`。
- `/hm:review` 继续只用于显式复查、纠错或处理旧 pending 残留。

## [2.9.0] — 2026-06-02

**主题：PRD Sync Candidate Surface**

v2.9.0 把原本只存在于 `session-distill.py` 里的 `prd-sync` 半成品命令收束成了
正式的 maintenance / review bridge。`/hm:prd-sync` 现在和其它 `/hm:*`
维护入口一样，有明确的用户面文档、OpenSpec contract、测试覆盖和 candidate-only
边界：默认 dry-run，只预览命中的 bundled packets 与 topic；显式 `--apply`
时也只会写 `prd-distilled/*.md` 候选笔记，不会越权直接修改正式 PRD、roadmap、
knowledge-base 或 confirmed truth。

### Added

- **v2.9.0 PRD sync maintenance entry**：新增正式 `/hm:prd-sync [--apply]`
  维护入口文档、plugin command、session-distill reference 与 install 输出。
- **projectless boundary**：`prd-sync` 不再要求项目 cwd / `--project` 解析，
  作为 maintenance entry 可以直接运行。
- **candidate-only output contract**：`--apply` 只写 `prd-distilled/*.md`
  candidate 文件；dry-run 不落盘，并明确声明 canonical PRD/roadmap docs
  保持不变。
- **focused regression coverage**：新增 no-bundles、dry-run、apply、
  bundled-only scanning 与 parser projectless 覆盖。

### Boundaries

- `prd-sync` 只读取 manifest 中 `bundled` 的 packet。
- 它不是 `/hm:distill` 主链，也不会自动改产品文档。
- 任何正式 PRD/roadmap 更新仍然需要后续人工或 agent review。

## [2.8.2] — 2026-06-02

**主题：Session-Distill Maintenance Surfaces**

v2.8.2 把已经存在于 `session-distill` 工具、slash 命令文档和 repo-local
维护脚本中的 distill 后处理能力，正式收束成一条版本化维护面。`/hm:mark`、
`/hm:prune`、`/hm:review-kb`、`/hm:prune-kb`、`/hm:verify-entry` 现在不再只是
“工具存在”，而是有明确 guardrail、cleanup 边界、review baseline、backup-first
约束和 reminder-only 非阻断契约。

### Added

- **v2.8.0 session closure and manifest cleanup**：`/hm:mark <session-id> distilled [--keep-raw]`
  现在有统一的 closure guardrail helper；`/hm:prune` 只允许清理
  `distilled/skipped` 且 `source_missing` 的 manifest 占位，不再接受未处理状态。
- **v2.8.1 knowledge-base review and prune**：`/hm:review-kb` 的 status model
  固定为 `stable / needs-review / stale / superseded`，review baseline 固定写
  `reviewed_at` / `total_entries` / `summary`；`/hm:prune-kb` 只允许清理
  `stale/superseded`，并保持 backup-first 与 dry-run 不落盘。
- **v2.8.2 targeted verification and reminder surfaces**：`/hm:verify-entry` 的
  session-id / keyword 命中与 grill-style recheck questions 被正式锁定；KB growth、
  packet overlap、note overlap reminder 被固定为 summary-only、non-blocking。

### Boundaries

- 这些维护入口仍然是 slash-first、自然语言优先；repo-local script 只是实现层。
- `mark/prune/review-kb/prune-kb/verify-entry` 都不会直接修改 canonical truth。
- reminder 只给建议，不会自动 prune、auto-supersede、也不会阻断 distill 成功返回。

## [2.7.2] — 2026-06-02

**主题：Cross-Project Skills and Controlled Activation**

v2.7.2 把 v1.8 的 project-scoped procedural skill 扩展成一套显式、可审核的
cross-project skill runtime。shared skill 只能通过 review 提升，默认 skill search /
wake 仍保持 project-scoped；Agent 只有在显式请求 shared search、skill hint 或
improvement/deprecation review 时，才会进入这些新 surface。

### Added

- **v2.7.0 scope model foundation**：confirmed `Skill` 现在支持
  `scope=project|workspace|global`、`origin_project`、`source_ids`、
  `portability_notes` 与 `disabled_assumptions`；新旧 skill 默认保持
  `scope=project`，不启用 shared consumption。
- **v2.7.0 promotion candidate loop**：新增 reviewed `skill_promotion`
  candidate 与 MCP `suggest_skill_promotion` / `confirm_skill_promotion` /
  `reject_skill_promotion`；`list_candidates` 现在会返回
  `skill_promotion_candidates` 和 `skill_promotion_count`。
- **v2.7.0 explicit shared search**：MCP `search_skills` 新增显式
  `include_shared` / `shared_scope=exclude|include|only`，默认仍只返回
  project-scoped skills；shared-inclusive 结果会保留 project-first 排序。
- **v2.7.0 activation warnings and separate feedback**：shared skill 搜索结果
  新增 `activation_warnings`，在 activation 前暴露 portability warnings；
  project/shared skill 的 `record_skill_result` 继续维持各自独立的 usage counters。
- **v2.7.1 controlled skill activation**：MCP `wake` 新增显式
  `include_skill_hints` / `skill_hint_limit`，以 opt-in 方式追加 compact
  skill hints；同时新增 `get_skill` 读工具用于按 id 显式展开完整 skill。
- **v2.7.2 skill improvement suggestions**：新增 reviewed
  `skill_revision_suggestion` candidate、MCP `detect_skill_improvements` /
  `confirm_skill_revision` / `reject_skill_revision`，把低成功率 skill 转成
  待审改进建议，同时保持 confirmed skill 不被自动改写。
- **v2.7.2 duplicate suppression and shared-skill deprecation**：
  重复运行 improvement detector 不会为同一 skill 重复创建 pending revision
  suggestion；新增 `skill_deprecation_suggestion` 与 MCP
  `detect_skill_deprecations` / `confirm_skill_deprecation` /
  `reject_skill_deprecation`，让 stale/conflicting shared skill 经 review 后退役。

### Boundaries

- 默认 wake / skill search 仍不消费 workspace/global shared skills。
- shared skill 只能通过 reviewed promotion/deprecation/revision 流程变更，不会静默跨项目注入，也不会自动改写 confirmed skill。
- procedural steps 仍不会直接塞进默认 wake；完整 skill body 需通过显式 `get_skill` 展开。

## [2.6.3] — 2026-06-02

**主题：Compact Wake Renderer Experiment**

v2.6.3 把 v2.6.1 的 generated wiki bridge 接到一个显式 opt-in 的 compact wake
renderer 上。它提供低 token 的 claim/topic/entity/source-id 摘要，但仍然只是一层
renderer：默认 `wake` 不变，generated claims 不会被提升成 confirmed truth。

### Added

- **compact wake renderer**：MCP `wake` 新增 `renderer="compact"`，显式读取
  project-scoped generated wiki bridge artifacts 并返回 compact output。
- **compact payload loader**：`harness_mem/knowledge_cache.py` 新增 compact payload
  读取与渲染辅助，输出 claims、topics、entities 与 source ids。
- **focused regression coverage**：补充 generated-cache compact renderer 测试和 MCP
  `wake(renderer="compact")` 测试。
- **v2.6.3 OpenSpec change**：新增并完成
  `openspec/changes/v263-compact-wake-renderer/`。

### Boundaries

- `renderer="compact"` 是 opt-in；默认 `wake` 仍使用 confirmed-truth renderer。
- compact output 明确标记为 generated summary，不会伪装成 confirmed truth。
- generated-only 内容仍不会进入默认 `search_memory` truth surface。

---

## [2.6.2] — 2026-06-02

**主题：Contradiction and Stale Suggestions**

v2.6.2 把 `v2.3.1` 已有的 metabolism suggestion 能力真正接入 review surface，
并补上此前 deferred 的 supersede/contradiction proposer。这个版本仍然坚持
candidate-before-truth：系统可以提出 merge、stale、supersede suggestion，
但不会把 generated/wiki evidence 或 suggestion 自己偷偷注入默认 truth surface。

### Added

- **review surface for metabolism suggestions**：`list_candidates` 现在会返回
  `MergeSuggestionCandidate` 与 `StaleTruthSuggestionCandidate`，并暴露
  `merge_suggestion_count` / `stale_truth_suggestion_count`。
- **supersede proposer reactivated**：`harness_mem/commands/metabolism_pass.py`
  的 `_propose_supersedes(...)` 不再是空实现；它会针对 recent historical truth
  与 highly similar current truth 生成 pending `SupersedeCandidate`。
- **focused regression coverage**：补充 metabolism proposer、`metabolism_run`
  和 MCP review surface 的测试，锁定 merge/stale/supersede 三类 suggestion 的
  candidate-only contract。
- **v2.6.2 OpenSpec change**：新增并完成
  `openspec/changes/v262-candidate-review-surface-and-contradiction-boundary/`。

### Changed

- 正式版本号从 `2.6.1` bump 到 `2.6.2`。
- `docs/roadmap-v26.md` 同步更新为 v2.6.2 已完成。

### Boundaries

- supersede proposer 只创建 `SupersedeCandidate`；不会自动 confirm，也不会直接改 truth。
- merge/stale/supersede suggestion 仍然只出现在 review surface，不进入默认 `wake` /
  `search_memory` current-truth read path。
- generated/wiki evidence 仍然只作为 suggestion 的证据来源，不会变成 hidden truth。

---

## [2.6.1] — 2026-06-02

**主题：Wiki Bridge + Compact Claim Index**

v2.6.1 在 v2.6.0 的 knowledge-cache boundary 之上，补上最小可用的 generated
wiki bridge。accepted memory、confirmed rules、relation facts 与 curated docs
会被显式编译成 generated claim/topic/entity 索引，每条 claim 都保留 source drilldown，
但这些 generated outputs 仍然不会进入默认 wake 或 `search_memory` truth surface。

### Added

- **wiki bridge compiler**：`harness_mem/knowledge_cache.py` 新增 `rebuild_wiki_bridge(...)`，
  从 accepted memory、confirmed rules、relation facts 与 curated docs 编译 generated artifacts。
- **compact generated artifacts**：在 `knowledge-cache/generated/` 下生成
  `claims.json`、`topics.json`、`entities.json`，并把 source hash / counts /
  tracked outputs 写回增强版 `generated/index.json`。
- **claim drilldown pointers**：每条 generated claim 都携带 `source_refs`，可回到
  `memory_entry_id`、`confirmed_rule_id`、`relation_fact_id` 或 `curated_doc_path`。
- **explicit rebuild entry point**：
  `harness-mem maintenance rebuild-wiki-bridge --project <name>`。
- **doctor generated visibility**：`harness-mem doctor` 的 `Knowledge cache:` block
  现在显示 generated claim/topic/entity 计数，并在 source stale 时提示 rebuild。

### Changed

- 正式版本号从 `2.6.0` bump 到 `2.6.1`。
- `maintenance --help` / shell completion 同步纳入 `rebuild-wiki-bridge`。
- `docs/roadmap-v26.md` 与 `openspec/changes/v261-wiki-bridge-compact-index/tasks.md`
  同步更新为 v2.6.1 已完成。

### Boundaries

- generated wiki 仍然只落在 `knowledge-cache/generated/`，不写回 canonical truth。
- 默认 `wake` / `search_memory` 仍然只消费既有 accepted truth 与 verbatim surfaces。
- contradiction / stale / merge suggestions 仍留在 v2.6.2。

---

## [2.6.0] — 2026-05-31

**主题：Knowledge Cache Boundary**

v2.6.0 先落地 wiki bridge 之前最重要的边界层：accepted memory 与 curated docs
可以被显式声明为知识源，但 manual authority 与 generated outputs 不会混在一起，
更不会被偷偷当成 runtime truth。这个版本只做 layout、sync map、source hash、
stale/orphan visibility 和 cleanup；不编译 compact claim，也不生成 contradiction
suggestion。

### Added

- **project-scoped knowledge cache boundary**：新增 `harness_mem/knowledge_cache.py`，
  为每个项目建立 `knowledge-cache/manual/` 与 `knowledge-cache/generated/` 的显式分层，
  并持久化 `sync-map.json`、`source-manifest.json` 与 generated `index.json`。
- **source authority + source hash**：accepted memory snapshot 与 `ProjectProfile.curated_doc_paths`
  会生成 `KnowledgeSourceEntry`，记录 `source_kind`、`authority`、`target_path`、`source_hash`
  与 `exists` 状态，为后续增量 wiki compile / stale detection 打地基。
- **`ProjectProfile.curated_doc_paths`**：project profile 现在可以显式声明 curated docs，
  CLI profile 展示与 MCP `get_project_profile` / `update_project_profile` 均已对齐。
- **knowledge cache doctor visibility**：`harness-mem doctor` 新增 `Knowledge cache:` block，
  显示 manual/generated 边界、source count、curated doc count、sync map 是否已准备、
  stale/missing source 数量，以及 orphaned generated outputs 的 cleanup 指针。
- **maintenance actions**：
  - `harness-mem maintenance prepare-knowledge-cache --project <name>`
  - `harness-mem maintenance cleanup-generated-cache --project <name> [--apply]`
- **v2.6.0 OpenSpec change**：新增 `openspec/changes/v260-knowledge-cache-boundary/`
  记录 proposal/tasks/spec。

### Changed

- 正式版本号从 `2.5.1` bump 到 `2.6.0`。
- `docs/roadmap-status.md` 与 `docs/roadmap-v26.md` 同步更新为 v2.6.0 已完成。

### Boundaries

- 不编译 wiki claim，不写 compact index。
- generated cache 不是 runtime truth，`wake` / `search_memory` 不消费 generated outputs。
- cleanup 只删除 orphaned generated outputs；不会删除 accepted memory、confirmed rules、
  relation facts、observations 或 curated docs。

## [2.5.1] — 2026-05-31

**主题：Context Assembly + Wake Renderer Hardening — v2.5.0 到 v2.5.1**

v2.5 把 `wake` 从"塞更多记忆"重构为**可解释、可预算、分层**的上下文组装：先由 v2.5.0 产出只读的 `ContextAssemblyPlan`（L0–L4 五层 + 每层 Budget / TruncationAccounting + 每条 source id / why-included），再由 v2.5.1 让渲染出的 `wake` 文本真正反映这份计划。本版本号一次性收口 v2.5.0–v2.5.1 两个切片。整条线保持 evidence-first 与 accepted-only 边界，Plan_Assembler 全程无副作用。

### Added

- **v2.5.0 Context Assembly Plan**：只读、可序列化的 `ContextAssemblyPlan` 数据结构（`harness_mem/core/schemas/context_assembly_plan.py`）—— 五层 L0（profile/identity）/ L1（essential truth）/ L2（active task）/ L3（topic recall）/ L4（raw evidence drilldown），每个 `PlanEntry` 携带 `source_ids` / `why_included` / `summary` / `truth_status`，每层带 `Budget`（`max_entries`）与 `TruncationAccounting`（available/included/dropped），L4 用 `DrilldownPointer` 只给展开指针。side-effect-free 的 `assemble_context_plan(...)`（`harness_mem/context_assembly.py`）组装于既有读面之上，不改 `wake`/`search` 输出、不写存储、不发 `RetrievalSignal`。

- **v2.5.1 Wake Renderer Hardening**：新增纯函数渲染模块 `harness_mem/commands/wake_render.py`（无 I/O / 无 store 访问 / 不 `print`）：`select_rendered_entries`（L1/L2 只保留 `confirmed_current` 真值 + 每层预算上限）、`render_truth_status_label`（historical/pending 醒目区分标记）、`render_source_id_display`（逐字符显示每条 source id，可溯源）、`render_entry_line`（摘要 + 真值标签 + Source_Id_Display + `📍` 出处标记）、`render_truncation_indicator`（从 `TruncationAccounting` 取数显示丢弃条数）、`render_wake_plan`（按固定顺序 L0 → L1 → L2 渲染，绝不渲染 L3/L4）。

### Changed

- **`cmd_wake_up` 改为计划驱动渲染**（`harness_mem/commands/wake.py`）：先 `assemble_context_plan` → `print(render_wake_plan(plan))` → 单独一遍去重应用既有的 `wake_surfaced` 信号 + 使用计数 touch（`touch_confirmed_rule` / `touch_memory_entry`，按 distinct source id 去重）→ 保留 Disclosure_Level token 摘要行。plan 组装失败时先报错并返回非零码，不输出任何 plan-backed 段。
- **被取代的旧 wake 扁平格式**：cold-start `wake` 的 `# Confirmed Rules` / `# Relation Facts` / `# Memory Entries` / bucket-quota 块、v2.3.1 weak-link `### Recent active` / `### Stable / quiet` 子标题、每条规则的使用徽章均被分层格式取代。confirmed rules 与 accepted current-truth entries 改在 L1（`# Essential Truth`）下出现；relation facts 属 L3（query-driven），无 query 的 cold-start wake 不再渲染（检索仍可经 `search`/`search_memory`）。
- **边界保持**：`ContextAssemblyPlan` schema 与 Plan_Assembler 选择逻辑在 v2.5.1 未改动（Req 9.2）；既有 `wake_surfaced` 信号 + touch 副作用、MCP stdout 纯净性均完好保留；未引入 `file_context`（推迟到 v2.5.2）、wiki bridge 或 contradiction/stale-truth 建议生成。
- 版本号从 `2.4.3` bump 到 `2.5.1`（`pyproject.toml` + `harness_mem/__init__.py`）。
- `docs/roadmap-v25.md`、`docs/roadmap-status.md`、`docs/reference-projects.md` 同步更新以反映 v2.5.0–v2.5.1 已落地与新的分层 wake 形态。

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

