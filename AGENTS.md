# AGENTS.md（事 · Facts）

> 项目事实：本文件回答“这个仓库现在是什么样、能力边界在哪里、如何验证”。只记录能从当前仓库文件核对的事实；协作方法见 `CLAUDE.md`，产品与开发者体验见 `DESIGN.md`。

## AI 入口文档分工

事、法、设共同构成 AI 入口，但职责不同：

```text
法（CLAUDE.md）     — 如何协作、如何裁决冲突
  → 事（AGENTS.md） — 仓库当前是什么、去哪里改、如何验证
  → 设（DESIGN.md） — CLI、MCP、宿主命令与文档体验
  → docs/           — 详细合同、路线图、验收和历史背景
```

| 文件 | 角色 | 职责 |
| --- | --- | --- |
| `AGENTS.md` | 事 · Facts | 当前版本、功能架构、代码 owner、命令、边界、门禁和真值索引 |
| `CLAUDE.md` | 法 · Protocol | 决策优先级、证据要求、开发流程、数据安全和结果声明规则 |
| `DESIGN.md` | 设 · Design | 产品、视觉、内容、CLI/MCP/IDE 与文档 DX 方向 |
| `docs/memory-adoption.md` | 五模块详细合同 | 各模块处理单位、职责、非职责、质量信号和数据边界 |
| `docs/roadmap.md` | 当前版本与下一施工列车 | 已发布能力、历史计划、下一阶段及明确不包含的范围 |
| `.codex/outcomes.json` | 用户结果合同 | Hook、蒸馏、Dream、Note、清理和检索等运行时结果的直接探针 |

`docs/` 是详细真值的承载位置，不应被旧叙事当作高于当前代码的指令。代码、manifest、测试和入口文档发生冲突时，先查当前实现与可执行证据，再修正文档；不要静默选择更符合预期但已过期的说法。

## 项目概览

`harness-mem` 是面向 AI Agent 的本地优先、可审计、可插拔记忆后端。Agent 通过统一 MCP surface 使用项目记忆；Claude Code、Codex、Cursor、Grok、Hermes、OpenCode 和 Antigravity 通过各自原生命令与 Hook 接入同一运行时。

- Python 包：`harness-mem`，当前发布版本 `0.9.26`；版本真值在 `pyproject.toml` 与 `harness_mem/__init__.py`。
- Rust helper crate：`harness_mem_core_rs`，crate 版本 `4.0.3`；它不是 Python 包版本。
- Python 要求：`>=3.9`。
- 分发：GitHub Releases 的原生 wheel 与 sdist，不发布到 PyPI。
- 日常用户动作：`status`、`wake`、`search`、`search-all`、`distill`、`review`、`dream`。
- CLI 是安装、配置、诊断、集成和维护面；MCP 是 Agent 日常记忆面。

## 当前版本与目标架构边界

`0.9.22` 已实现会话生命周期、无损提取、逐点验证、SQLite 当前知识、job 范围临时处理材料、干净检索，以及显式授权的 detached semantic execution。当前 normal wake/search 已把 raw Observation 和内部审计元数据隔离到 deep recall 或诊断面。

`0.9.23` 增加用户配置中的 operator-owned semantic provider profile，以及只针对完整、可重开来源的终态 Dream 复核；`0.9.24` 为拒绝强制 tool 输出的 Anthropic 兼容网关增加经严格 schema 校验的无工具 JSON 模式；`0.9.25` 让 Hook 触发的会话由 Dream 统一执行，并修复截断来源退役、Dream undo、provider 失败终态和 Hook receipt 关联的 fail-closed 边界；`0.9.26` 将已授权后台收敛为 **`distill.autonomous.enabled=true` + 当前宿主 CLI**（`{host}_cli` 诚实回执），CLI 路径不再要求 `semantic.execution.profile` 或 user-config provider 表。人工 `distill` 留在当前宿主。

兼容 `MemoryEntry` 历史行仍可读取，但新知识不再把 candidate、evidence、decision 和 truth 混成一个对象。`canonical.sqlite` 中的 `knowledge_entries` 是当前知识 authority；新候选、证据和拟议归纳决定属于 job 范围临时材料，成功终态经证明后按策略清理；最小知识来源与必要 undo 版本独立关联；Markdown 仅在阅读/导出时生成。六会话冻结 oracle、真实 Hook 与 14 项 outcome 已通过。普通开发、启动或文档更新均不得迁移真实记忆；仅限操作员单独授权的、明确项目范围的维护运行可以重验来源、原子重写或可逆地退役历史行。一次已授权的 `harness-mem` 范围收敛已完成，其他项目和后续历史数据仍需新的明确授权。

`0.9.13-0.9.15` 是已被下一列车取代的历史质量计划记录，不是当前已发布版本，也不能作为“物理真值分离已经完成”的证据。

## 五模块功能架构合同

```text
0. 会话接入与生命周期
→ 1. 提取
→ 2. 逐点验证
→ 3. 归纳吸收
→ 4. 检索与使用
```

这是五个可独立迭代、归因和衡量的产品模块，不是用户每天必须依次执行的命令清单。

### 0. 会话接入与生命周期

- **处理单位：** 一个原生 session 及其一个不可变 revision；运行时继续管理 chunk、job、lease 和 receipt。
- **负责：** 七宿主接入、项目与授权解析、不可变 source version、无损分块、增量 revision、hash/完整性校验、队列/并发/幂等/重试、Hook/final receipt 绑定，以及按策略保留或清理来源。Hook 只创建或推进 job，并发出带 session/revision 引用的 Dream 活动信号；它不执行语义判断。
- **不负责：** 判断会话中的陈述是否值得长期记忆。
- **质量信号：** 不漏 session、不漏内容、不重复处理；revision 可重构；重试后有可靠终态；receipt 与 session/job 可证明绑定；来源不会越权删除。
- **主要 owner：** `harness_mem/adapters/`、`harness_mem/host_entry/`、`harness_mem/transcript_chunking.py`、`harness_mem/storage/transcript_store.py`、`harness_mem/storage/session_distill_store.py`、`harness_mem/hook_*.py`、`harness_mem/native_source_cleanup.py`。

### 1. 提取

- **处理单位：** 一场会话中 0～12 个可独立处理的 promotion point。
- **负责：** 从完整会话中高召回地发现可能有长期价值的独立知识点，为每个点输出待验证说法与可回查的 source location；保留完整 manifest、semantic/raw drilldown 和零候选挑战。
- **不负责：** 判断证据是否成立，也不决定 disposition、长期知识标题或项目模块，更不直接写长期知识。
- **质量信号：** 重要知识点不漏；整场会话不被压成一个大结论；每个点足够窄，可独立验证和处置；source coverage 保持无损。
- **主要 owner：** `harness_mem/mcp/distill_handlers.py`、`harness_mem/mcp/distill_projection.py`、`harness_mem/distill_context.py`、`harness_mem/core/schemas/session_distill.py`、`code/tools/hm-distill/SKILL.md`。

### 2. 逐点验证

- **处理单位：** 一个 promotion point，而不是整个 session。
- **负责：** 检查 reference integrity 与当前语义支持：用户、文件或来源是否真的说过该内容，digest 是否仍匹配，代码/配置/用户决定是否仍然有效。
- **不负责：** 判断长期价值，也不修改长期知识。`ANSWERED` 只表示证据问题已回答、可以进入吸收判断，不代表必须写入。
- **结果：** `ANSWERED`、`PARTIAL`、`UNANSWERED`、`CONTRADICTED`、`STALE`、`NOT_APPLICABLE`。
- **质量信号：** 不把用户提及当成既定事实；不把旧实现当成当前实现；一个点失败不污染同会话其他点；后续纠错可用于校准误判。
- **主要 owner：** `harness_mem/commands/evidence_admission.py`、`harness_mem/core/schemas/evidence.py` 及 candidate evidence envelope。

### 3. 归纳吸收

- **处理单位：** 一个已经验证的 promotion point，与当前项目知识进行对照。
- **负责：** 判断 durable value；把 session 说法改写为知识语言；保持一条知识一个事实；拆分过宽候选；与 SQLite 当前知识做语义去重和替换；根据整个项目已验证知识自然组织功能模块，不使用硬编码模块白名单。
- **处置：** `add`、`refine`、`confirm`、`supersede`、`no_write`、`handoff`、`defer`、`conflict`、`reject`。
- **不负责：** 获取原始来源，也不把 provenance、candidate JSON 或 audit envelope 默认暴露给正常检索。
- **质量信号：** 垃圾写入趋近于零；不宽、不重、不混；同一事实不换措辞重复写；设计目标不冒充当前实现；candidate、audit、handoff 与长期知识保持区别。
- **主要 owner：** `harness_mem/commands/assimilation.py`、`harness_mem/core/schemas/assimilation.py`、`harness_mem/storage/candidate_store.py`、`harness_mem/storage/truth_store.py`、`harness_mem/mcp/governance_handlers.py`。
- **长期知识形态：** SQLite `knowledge_entries` 是项目当前长期知识单一真源；行内只保留稳定内部 ID、项目、自然模块路径、具体标题、一条知识正文和验证日期，最小真实来源独立关联。内部类型、处置、job 和理由码不进入正式知识或默认展示。
- **当前兼容边界：** `0.9.22` 发布路径（并由 `0.9.23` 至 `0.9.25` 延续）已分离干净当前知识、临时 job 材料和最小来源/undo 数据；旧 `MemoryEntry` 兼容行不会因升级自动迁移、删除或改写。

### 4. 检索与使用

- **处理单位：** 一个 task/query 及为其返回的长期知识。
- **负责：** 从 SQLite 当前知识单一真源或同代派生索引读取，完成项目隔离、相关性排序、当前知识优先、重复折叠，隐藏 superseded/rejected/deferred/raw 内容，提供干净的标题 + 正文默认输出，并记录有界的 `used`、`ignored`、`misleading`、`stale` 反馈。
- **不负责：** 在正常结果中暴露 transcript、candidate、Answer Packet、Note、审计原因、内部 ID、hash 或历史版本。
- **质量信号：** 召回率、精确率、去重、最小充分上下文成本，以及默认结果的审计噪声/过期知识泄漏率。
- **主要 owner：** `harness_mem/mcp/read_*`、`harness_mem/search/`、`harness_mem/wake_selection.py`、`harness_mem/context_assembly.py`、`harness_mem/storage/derived_index.py`。

### Review 与 Dream 治理反馈

Review 与 Dream 是跨阶段 3～4 的治理反馈能力，不是线性第六阶段，也不是每天必经的人工写入门。会话可从两条入口进入同一套提取、验证与吸收合同：

```text
人工 `distill`
→ 当前宿主读取会话
→ 提取 → 验证 → 归纳吸收

Hook
→ 保存会话与 job，发出带来源引用的 Dream 活动信号
→ Dream 在后台读取该会话和项目当前知识/来源/反馈
→ 提取或比较 → 验证 → 归纳吸收
→ 当前长期知识
```

二者都不能绕过逐点验证直接改写当前真相；发生 durable truth 变更时必须保留可审计、可撤销的记录。

### 质量问题归因

| 现象 | 首要归因模块 |
| --- | --- |
| 原生会话丢失、revision 不完整、receipt 不可靠、来源误删 | 0. 会话接入与生命周期 |
| 本应记住的知识点没有被发现 | 1. 提取 |
| 写入了证据不成立或已经过期的知识 | 2. 逐点验证 |
| 写入垃圾、重复、过宽或混杂知识 | 3. 归纳吸收 |
| 找不到已有知识，或 normal 结果混入 raw/audit/历史噪声 | 4. 检索与使用 |

## Workspace 结构

- `harness_mem/`：Python runtime 唯一实现位置。
  - `adapters/`：七宿主 transcript adapter、扫描和 snapshot 能力。
  - `autonomous/`：显式授权的 detached semantic provider 边界。
  - `commands/`：CLI 与内部业务编排，包括 evidence admission、assimilation、Dream、wake 和维护。
  - `core/interfaces/`、`core/schemas/`：存储接口和领域 schema。
  - `host_entry/`：`harness-mem-hook` 原生入口。
  - `integration/`：宿主命令、Hook template、安装和修复。
  - `mcp/`：公开 tool spec/registry、handler、projection、response view 和 server。
  - `search/`、`index_fabric/`、`embedding/`：检索、索引和可选向量能力。
  - `storage/`：canonical SQLite 当前知识、job-scoped 处理材料、transcript ledger、派生索引和迁移。
  - `qualification/`：可独立执行的运行时 outcome probe 与验收 fixture。
- `code/crates/harness_mem_core_rs/`：PyO3 Rust helper，提供确定性热路径能力。
- `code/plugins/harness-mem/`：随仓库分发的 Agent client 集成资产。
- `code/tools/hm-distill/`：MCP distill 的纯 Agent 指令；不得承载 runtime 实现。
- `code/tools/outcome-verifier/`：项目内 outcome verification 脚本副本。
- `code/tests/`：unit、contract、fixture、host replay、qualification 和 outcome tests。
- `docs/`：架构、兼容、验收、运维和 roadmap 详细文档。
- `code/scripts/`：descriptor canonicalization 等仓库维护脚本。
- `.agents/`、`.claude/`、`.cursor/`、`.grok/`、`.opencode/`：项目内宿主命令、skill 或 workflow 镜像；不是独立 runtime 真值。
- `.codex/agents/`：项目内 specialist agent 定义；`.codex/outcomes.json` 是用户结果合同。

## 关键技术与持久化

- 语言：Python 3.9+、Rust 2021。
- 构建：Maturin；Rust/Python 绑定使用 PyO3 `abi3-py39`。
- 核心依赖：Pydantic、`sqlite-utils`、`tomli_w`。
- 可选检索：`sentence-transformers`、`sqlite-vec`、NumPy。
- Python lock：`uv.lock`；Rust lock：`Cargo.lock`。
- 默认数据根：`~/.harness-mem/data`。
- 用户配置：`~/.harness-mem/config.toml`；项目配置：`<project>/.harness-mem.toml`。
- canonical SQLite 是当前长期知识的持久化 authority；job-scoped candidate/evidence/proposed-decision 只为重试和未解决状态暂存，成功终态经证明后清理；transcript ledger 是原始会话 authority；FTS/vector/其他 derived index 和按需 Markdown 可由 SQLite 重建，不能反向成为真值源。
- legacy entity JSON 从 `0.9.6` 起弃用但在整个 `0.9.x` 保持可读，最早移除时间同时受 `1.0.0` 与 `2027-01-31` 约束；普通启动不静默切换存储 authority。

## 公共入口与能力边界

`pyproject.toml` 声明三个 console entry：

| 入口 | 实现 | 主要职责 |
| --- | --- | --- |
| `harness-mem` | `harness_mem.cli:main` | 初始化、配置、Doctor、集成和维护 |
| `harness-mem-mcp` | `harness_mem.mcp.server:main` | Agent 日常记忆工具面 |
| `harness-mem-hook` | `harness_mem.host_entry.__main__:main` | 宿主 SessionStart/Stop 等生命周期事件 |

MCP schema、handler、cluster/registry 与 descriptor 必须保持同一组 27 个公开工具。新增公共工具不是普通实现细节；先修改 canonical tool specs，再同步生成面并运行公共 surface contract。

| 用户动作 | 架构位置 |
| --- | --- |
| `status` | 汇总阶段 0～4 的真实状态 |
| `wake` | 阶段 4：加载干净、紧凑的当前项目上下文 |
| `search` / `search-all` | 阶段 4：项目内或显式跨项目检索 |
| `distill` | 人工显式入口；由当前宿主编排阶段 1～3 |
| `review` | 事后人工审计、纠错、undo 和 supersede |
| `dream` | 唯一无人值守的执行者；处理 Hook 触发会话并进行项目级治理，再回到验证与吸收 |
| Hook、archive maintenance | 阶段 0 生命周期入口；Hook 只排队和唤醒 Dream |

## 数据、隐私与运行时边界

### 术语（减少歧义）

详细说明见 **[`docs/background-memory.md`](docs/background-memory.md)**。下表仅作最短索引：

| 说法 | 指什么 | 不是什么 |
| --- | --- | --- |
| **本机 harness-mem** | Dream、autonomous worker、finalize、SQLite | 外部 model API 或宿主 IDE |
| **receipt / fingerprint** | 本机 autonomous 审计回执；代码版与配置版的 SHA256 | 长期记忆或 Note 正文 |
| **`distill.autonomous.enabled`** | 项目开关：`true` = 后台 Agent（默认 `mode=agent`）；`false` = 关 | 不是人工 `distill` 开关 |
| **`semantic.execution.mode`** | 默认 **`agent`**（不必写）；后台全 Agent，唯一硬限制 = Hook 不得重入 | 不是用户要选的第三档位名 |
| **`semantic.execution.restricted`** | **遗留键**（0.9.25 代码仍读）；`false` 等同关后台。新文档以 `enabled=false` 为准 | 不是 Codex `--sandbox`；不要再用它表达「只禁 Hook」 |
| **`execution_mode`（receipt）** | 回执：`agent` + `{host}_cli` = 宿主 CLI 成功 | 非 `{host}_cli` 名不能冒充 Agent |
| **`provider.name`（receipt）** | 成功路径：`{host}_cli`（如 `codex_cli`、`hermes_cli`、`claude-code_cli`、`opencode_cli`） | HTTP 名（如 `anthropic_messages:…`）不能冒充 Agent |
| **outcome** | 14 条用户结果合同 + 本机探针 | 普通单元测试 |

**产品默认 vs 当前实现（0.9.26）：**

| | 产品默认（文档合同） | 当前代码实现 |
| --- | --- | --- |
| 开后台 | `enabled=true` | `build_semantic_executor` → 当前 `host_client` 的 CLI |
| 关后台 | **`enabled=false`** | legacy `restricted=false` 亦 effective 关 |
| 传输 / 凭据 | 在**当前宿主 CLI** 配置（Codex/Hermes/Claude Code/OpenCode 等各自 CLI） | harness-mem 不承载 endpoint / api_key |
| 写库 | 本机 Answer Gate + finalize | 不变 |

**无人值守写记忆：** Hook → **本机 Dream/worker** 调后台 model 拿 JSON → Answer Gate + assimilation → **同一套本机代码** finalize 并写 Note/SQLite。不是「Dream 不写、别的 runtime 写」。

- transcript revision 与 Observation 是证据，不是长期事实；没有原始 transcript 的旧 Observation 标记为 `legacy_partial`，只供审计。
- Agent 可以提出 evidence refs，但不能自行声明 `ANSWERED`；Answer Gate 由**本机 harness-mem**（证据重验模块）派生。
- **后台语义** 经 **宿主 CLI Agent** 返回受 schema 约束的 JSON；**本机 harness-mem（含 Dream/worker）** 才能创建候选、`finalize`、写 Note 和修改治理状态。
- normal wake/search 返回当前 governed truth；raw transcript、candidate、Note、Answer Packet、provenance 和内部 ID 只在显式 audit/deep recall 出现。
- Session Note 最新视图位于 `~/.codex/hm-distill/sessions/<session-id>.md`，不可变 job-bound 版本位于 `~/.codex/hm-distill/sessions/revisions/<job-id>/<session-id>.md`；Note 是历史可读/审计产物，不是当前项目真相。
- `<private>...</private>` 与项目 `[capture]` ignore 在落盘前生效；被排除内容不得进入 revision、chunk、Observation 或索引。
- source cleanup 只有在策略授权、adapter 支持 session-scoped deletion 且 quiet/CAS/hash 检查通过时才执行；共享或不安全容器保持不动并报告 `unsupported`。
- `maintenance erase` 默认 preview；`--apply` 才执行。不得为删除一个 session unlink 整个共享历史容器。
- `.harness-mem` 数据根、原生宿主历史、Notes、receipts、runtime reports 和 `.codex/` 运行证据不得作为无关代码/文档任务的副作用被修改或清理。
- autonomous model use：**产品合同**为 `distill.autonomous.enabled=true` + **当前 host_client** 走对应宿主 CLI（`codex_cli`、`hermes_cli`、`claude-code_cli`、`opencode_cli` 等；七宿主同一规则，Hook 传谁就用谁）。传输与密钥在该宿主 CLI 配置。**关后台只用 `enabled=false`。** 无 HTTP profile、无 `semantic.execution.profile`、无 enabled=false 时的 HTTP fallback。详见 [`docs/background-memory.md`](docs/background-memory.md)。

## 构建、测试与开发命令

从仓库根目录执行：

| 目的 | 命令 | 来源 |
| --- | --- | --- |
| Python compile | `python -m compileall harness_mem` | `README.md` |
| Ruff | `python -m ruff check harness_mem code/plugins code/tools` | `README.md` |
| Mypy | `python -m mypy harness_mem` | `README.md` |
| Version alignment preflight | `python -m pytest -q code/tests/test_package_version_alignment.py code/tests/test_version_drift.py` | `README.md` |
| 快速 PR lane | `python -m pytest -q -m "not release_gate"` | `README.md` |
| 完整 Python lane | `python -m pytest -q` | `README.md` |
| CLI smoke | `python -m harness_mem.cli --help` | `README.md` |
| Rust workspace | `cargo test --workspace` | `README.md` |
| MCP descriptor 收敛 | `python code/scripts/ensure_mcps_canonical.py` | `README.md` |
| 用户结果合同 | `python code/tools/outcome-verifier/scripts/verify_outcomes.py --config .codex/outcomes.json --output .tmp/outcome-verifier/harness-mem-report.json` | `.codex/outcomes.json` |

快速 lane 只跳过四组穷举的 60-case retrieval replay；完整 Python lane 是 release lane 的基础，不等于所有异步或真实宿主用户结果已经发生。

## 定向验证与关键门禁

| 改动范围 | 最小相关门禁 | 保护的合同 |
| --- | --- | --- |
| MCP tool spec、handler、descriptor | `code/tests/test_mcp_public_surface_contract.py`、`code/tests/test_mcp_exported_tools.py`、`code/scripts/ensure_mcps_canonical.py` | 27-tool surface 一致，不产生 registry 漂移 |
| package / plugin / public install version | `code/tests/test_package_version_alignment.py`、`code/tests/test_version_drift.py` | 源码、插件 manifest、公开安装说明与成熟度快照同版；应在完整 suite 前先跑 |
| transcript、adapter、Hook、job lifecycle | `code/tests/test_lossless_distill_mcp.py`、`code/tests/test_transcript_evidence.py`、对应 `test_lossless_*_adapter.py` | revision/chunk 无损、job/receipt 绑定、项目隔离 |
| evidence admission / Answer Gate | `code/tests/test_evidence_admission.py` | repository/user/transcript 证据类型、digest 与 fail-closed 状态 |
| assimilation / truth mutation | `code/tests/test_assimilation_runtime.py`、`code/tests/test_assimilation_shadow.py` | 每点独立处置、完整覆盖、无重复、冲突不写 |
| normal wake/search | `code/tests/test_clean_retrieval_outcome.py`、`code/tests/test_user_facing_memory_flow_contract.py` | 当前真相可读，raw/audit/provisional 不泄漏 |
| Dream / Review | `code/tests/test_dream_maintenance_contract.py` | 治理反馈、终态、审计与 undo 边界 |
| storage / cleanup / migration | `code/tests/test_native_source_cleanup.py`、`code/tests/test_processed_source_cleanup.py`、canonical store/migration tests | receipt-first、安全删除、authority 不静默变化 |
| 七宿主支持声明 | `code/tests/test_host_replay_qualification.py` 与各宿主 fixture | Hook 与 transcript capability 分开证明，不能由一个推断另一个 |
| 模块拆分或 facade | `code/tests/test_module_convergence_boundaries.py` | handler/storage/Doctor owner 不重新膨胀或吸回已拆职责 |
| 真实运行结果声明 | `.codex/outcomes.json` + outcome verifier | Hook→job→Note→retrieval、Dream、清理等直接结果 |

门禁的“通过”只证明其声明范围。代码存在、配置存在、mock 通过、任务排队或接口返回 `completed` 都不能替代用户结果探针。

## 关键实现边界

- `harness_mem/` 是 runtime 唯一代码真值；`code/tools/hm-distill/` 和宿主命令是指令/适配层，不得复制一套运行时。
- `harness_mem/mcp/tool_specs.py`、tool registry/handlers 与生成 descriptor 必须收敛；不要在某个宿主镜像中私自新增工具语义。
- `LocalStructuredStore`、MCP read facade 和 Doctor 已有体积/职责门禁；新增行为进入对应领域 owner，不把拆出的逻辑重新塞回 facade。
- SQLite `knowledge_entries` 是当前长期知识的持久化 truth；FTS/vector、compact views、Markdown 和 summaries 是可重建索引或投影层。
- 提取只输出待验证说法与来源定位；`disposition`、标题和自然功能模块全部由归纳吸收阶段决定。项目模块不设硬编码白名单，未知模块名也不能仅因非空就自动写入，必须由已验证知识和项目级归纳结果支持。
- extraction、verification、assimilation 是三个不同判断：发现了候选不等于证据成立，证据成立也不等于必须写入。
- 一场会话可以同时有已回答的 durable point 和未完成 handoff；无关 handoff 不应否决其他已回答 point。
- `finalize_session_distill` 是人工会话蒸馏 job 的唯一提交点；不要额外调用平行 auto-review 或另一个隐式后台蒸馏管线。Hook 触发的会话由 Dream 统一处理。

## AI Assistant Tool Routing

### 项目内日常记忆入口

| 场景 | 入口 |
| --- | --- |
| 新 session 恢复上下文 | `wake` / `$hm-wake` / 对应宿主命令 |
| 项目内查询历史知识 | `search` / `$hm-search` |
| 显式跨项目借鉴 | `search-all` / `$hm-search-all` |
| 立即整理近期会话 | `distill` / `$hm-distill`，遵循 `code/tools/hm-distill/SKILL.md` |
| 审计、纠错、撤销 | `review` / `$hm-review` |
| 查看或显式触发治理维护 | `dream` / `$hm-dream` |
| 诊断项目记忆状态 | `status` / `$hm-status` |

物理镜像位于 `.agents/skills/`、`.agents/workflows/`、`.claude/commands/`、`.cursor/commands/`、`.grok/skills/` 和 `.opencode/commands/`。它们应保持同义；插件或用户全局 skill 不得误写成项目 runtime 依赖。

### 验证与维护入口

| 场景 | 入口 |
| --- | --- |
| 用户可见运行结果验收 | `outcome-verifier` + `.codex/outcomes.json` |
| MCP descriptor 修复 | `python code/scripts/ensure_mcps_canonical.py` |
| 存储与 Hook 诊断 | `harness-mem doctor`，只读探测并输出分级 recovery plan |
| 跨宿主 Hook 修复 | `harness-mem integration hooks sync --client all --project-root . --force` |
| 首次或大重置 AI 入口 | 外部 `/harness-init`；本仓 `.cursor/commands/harness-init.md` 是 Cursor adapter，不是 runtime skill |

## 文档真值入口

| 主题 | 文件 | 状态/用途 |
| --- | --- | --- |
| 公共产品与安装 | `README.md`、`README.zh-CN.md` | 用户主入口；公开行为变更需同步 |
| 五模块详细合同 | `docs/memory-adoption.md` | 当前概念 owner；含模块单位、职责、非职责和质量信号 |
| 当前版本与下一列车 | `docs/roadmap.md` | 区分已发布、折叠版本、历史计划和 Next train |
| SQLite 当前知识收敛 | `docs/roadmap/knowledge-truth-separation.md` | `0.9.22` 发布实现（`0.9.23` 至 `0.9.25` 延续）；普通运行不迁移真实旧记忆，已授权收敛必须项目隔离、来源重验且可逆 |
| Distill 验收矩阵 | `docs/distill-test-plan.md` | fixture、路径矩阵、停止条件和报告格式 |
| 自动晋升治理 | `docs/auto-promoted-memory-governance.md` | compatibility contract、状态和读路径 |
| 宿主 Hook/adapter | `docs/ide-hook-adapter-matrix.md` | 七宿主能力、安装位置和支持证据 |
| Legacy storage | `docs/storage-legacy-lifecycle.md` | authority、迁移、回滚和支持截止策略 |
| 自动检索策略 | `docs/autopilot-search-policy.md` | 触发条件、回执和 abstention |
| 用户结果 | `.codex/outcomes.json` | 直接探针合同，不是普通单元测试列表 |
| 后台记忆说明 | `docs/background-memory.md` | enabled、profile、CLI 回执、status.reason |

## 快速参考

- 协作协议：`CLAUDE.md`
- 产品与 DX：`DESIGN.md`
- Python 包与版本：`pyproject.toml`、`harness_mem/__init__.py`
- CLI：`harness_mem/cli.py`
- MCP server：`harness_mem/mcp/server.py`
- Hook entry：`harness_mem/host_entry/__main__.py`
- 当前知识单一真源：`harness_mem/storage/knowledge_store.py`
- Canonical SQLite 与事务：`harness_mem/storage/canonical_store.py`
- 按需阅读投影：`harness_mem/knowledge_renderer.py`
- Distill 指令：`code/tools/hm-distill/SKILL.md`
- Outcome 合同：`.codex/outcomes.json`
- Cursor Harness rule：`.cursor/rules/harness.mdc`
