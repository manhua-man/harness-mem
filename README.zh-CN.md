<p align="center">
  <img src="docs/assets/harness-mem-logo.svg" alt="harness-mem logo" width="420" />
</p>

<h1 align="center">harness-mem</h1>

<p align="center">
  <strong>local-first、可审核、可插拔的 Agent 记忆后端。</strong>
</p>

<p align="center">
  <a href="README.md">English</a>
</p>

<p align="center">
  <a href="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml">
    <img src="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml/badge.svg" alt="public smoke status" />
  </a>
</p>

Agent 会读代码，但它通常不知道项目为什么变成现在这样：发布边界、历史决策、handoff、上轮 review 结论、哪些 claim 还不能写。

`harness-mem` 把这些内容变成本地记忆，通过单一 MCP memory surface 接给 Claude Code、Codex、Cursor、Grok、Hermes、OpenCode 和 Antigravity。新 Agent 用 `wake` 和按任务触发的 `search` 找回上下文，用 `distill` 整理近期 evidence，低风险内容可自动提升为可读记忆；`review` 是事后审计、纠错和 undo 入口，`dream` 负责维护 ledger。

触发入口（用户级安装一次，之后所有项目可见）：

- `/hm:*` 命令：`status`、`wake`、`search`、`search-all`、`distill`、`review`、`dream`。
- Agent MCP 调用：自然语言、skill 或 hook 触发 `wake/search/distill/review`。
- Hook：会话开始注入 wake context；任务过程中按需 search；save point / 会话结束执行 retention。distill 活跃槽最多 2 条，按 3:1 recent/oldest 公平补位，带失败退避和每日新 job 上限；每个 Agent task 可按顺序处理最多 2 条 job。没有 Agent 时明确显示 `waiting_for_agent`，不会声称后台已完成语义处理。
- CLI：只做 setup、doctor、config、integration 和 maintenance。

日常使用只需要三个意图：用 `wake/search` 继续工作，把可复用结果记住，或
review/undo 一条错误记忆。status 与 Dream 继续作为兼容的诊断和维护能力，
不是用户每天必须手工完成的额外步骤。

<p align="center">
  <img src="docs/assets/harness-mem-cold-start-flow.svg" alt="新 Agent 通过 wake、search、distill、review、dream 恢复跨会话项目上下文" width="900" />
</p>

## 主路径

```text
wake -> search -> distill -> review -> dream
```

| 步骤 | 作用 |
|---|---|
| `wake` | 会话开始从可读记忆生成项目简报。 |
| `search` | 当 `autopilot_search_tick` 检测到具体不确定性、冲突、工具失败、待写入 durable claim 需要 grounding、或长周期任务切换时，找回历史决策、规则和 handoff。 |
| `distill` | 校验全部原始 chunk，在自适应完整响应目标下读取覆盖优先的索引清单，选择完整语义窗口，再钻取候选级原文证据，最后做末尾审查、候选治理和 Dream。 |
| `review` | 事后审计、确认、拒绝、undo 或替代自动处理过的条目。 |
| `dream` | 维护 ledger、压缩过期状态，并在 save point / 会话结束后保留可回滚治理记录。 |

任务过程中的检索不是 always-on。PI 里的 `transformContext`、
`tool_result`、`prepareNextTurn`，Claude Code 的 `PostToolUse`，以及
Cursor 的 after-agent hook，都应映射到同一个 `autopilot_search_tick`
事件入口；`/hm:search` 只是客户端没有这类 hook 时的手动兜底。
`Stop` Hook 会保存不可变的原始 transcript revision，并排队它的全部有序 chunk。日常 `prepare_session_distill(evidence_mode="semantic", detail_level="compact")` 保留完整原文，由 runtime 校验并 checkpoint 每个 raw chunk，再返回包含全部 exchange 索引和风险信号的 compact manifest。预算约束的是 Agent 实际接收的完整序列化 MCP 响应，3k 只是兼容默认软目标；允许因完整覆盖或显式 drilldown 扩张，但 `response_budget` 必须报告真实 token 数与原因，绝不静默丢弃后半段 exchange。Agent 先选择最多 8 个完整语义窗口，再只为候选主张钻取 raw proof。`detail_level="full"` 与兼容 `raw` 模式只用于显式完整审计，raw chunk 不截断内容。完成会话末尾审查后才可用稳定幂等 ID 生成候选。检测到 decision、solution、preference、workflow、migration 或 handoff 信号时默认 fail-closed 为 `candidate_required`；只有读完完整窗口并给出针对该信号的 session-only 理由才能降级。`finalize_session_distill` 对当前 job 执行 scoped 自动治理并记录 `promoted` 或 `no_candidate`。已回答候选可以与无关的未完成 handoff 分开治理，但 review 未完整结束时不运行 Dream。默认结果与 Session Note 使用“标题 + 单一可验证事实 + 验证日期/状态”，内部 ID 只进入显式审计详情。`/hm:review` 是纠错和 undo 入口，不是日常晋升闸门。`/hm:distill` 是同一条可恢复管线的立即执行入口。Hook 只负责同步、排队和注入 Agent 工作，不能声称没有 Agent 时已完成总结；没有原始 transcript 的旧 Observation 仅供审计，标记为 `legacy_partial`。

新候选带 evidence basis 和 verification outcome。仓库事实必须引用
当前项目相对文件及其 SHA-256；用户偏好或决定引用 user role 的 exchange
摘要。只有 transcript 说法、证据缺失/变化或已冲突的候选不能进入长期 truth；
RelationFact 也走同一准入规则，旧 truth 不会被追溯重分类。

0.9.6 在不改变主流程的前提下收敛了安装面：MCP schema、handler、cluster 和
descriptor 注册表严格对应同一组 27 个公开工具；七宿主 hook 修复统一为一个
命令；公开配置只保留 10 个持久策略选择，旧 tuning 值仍可兼容读取。

0.9.9 不增加第二条产品路径，而是在现有边界上加固：有界的重启恢复、派生索引
原子重建、七宿主原生回放，以及安装、升级和恢复验收，都继续复用本地 SQLite、
Adapter、Dream 和 Doctor。详细回放指标只进入维护工件；日常 wake、status 和
distill 仍保持 compact。

Observation 只是证据，不是被记住的事实。wake 的近期索引会明确标成“非事实证据”；L1/L2 只展示结构化当前事实和仍有效的 handoff。被当前仓库版本推翻的旧发布/版本说法会标记冲突，或从 truth/active 层移除。

隐私策略在落盘前执行：可用 `<private>...</private>` 包裹敏感片段，也可在项目 `.harness-mem.toml` 的 `[capture]` 中配置忽略 client、session 和 source glob；被排除内容不会进入 raw revision、chunk、Observation 或索引。`[transcript].retention_days` 控制自动保留期（`0` 表示永久保留）。整理完成后的原文清理是另一个持久开关，默认关闭；用 `harness-mem config set distill.delete_source_after_complete true --scope user --confirm` 开启，项目配置可覆盖。`--confirm` 只在持久策略从关闭变为开启时要求；关闭策略以及后续每个会话的自动清理不再逐个确认。IDE 中用户明确说“开启 harness-mem 整理后删除原会话”，即可授权 Agent 执行这次带确认的配置写入。开启后会删除满足静默/CAS 校验的宿主会话源、local raw bytes、chunks、checkpoint result、Observation 和派生索引，同时保留并脱敏长期 Memory/Rule/Fact/Skill；每次结果明确为 `retained`、`deleted`、`partial_failure` 或 `unsupported`，且宿主删除前先写无内容 receipt。无法安全按会话事务删除的共享 SQLite/JSONL 会保持不动并报告 unsupported，绝不会删除整个共享历史文件。`harness-mem maintenance erase --project NAME --session-id ID` 默认预览，增加 `--apply` 后会删除可安全 CAS 的宿主原会话、raw revision、chunk、distill job、Observation、关联候选/事实以及 FTS/vector 索引。apply 会先持久化不含内容和原始标识的 receipt；共享或不安全的宿主容器保持不动并返回 partial failure，receipt 写入失败时不会开始删除。

旧 entity JSON reader 从 0.9.6 起弃用，但完整支持整个 0.9.x；最早删除门槛同时为 1.0.0 和 2027-01-31，以更晚者为准。旧数据只读启动不会静默切换存储权威，详见 [legacy storage lifecycle](docs/storage-legacy-lifecycle.md)。

运维诊断同样显式：Doctor 只读探测 SQLite，并把恢复动作分成 `safe_rebuild`、`snapshot_required`、`manual_review` 和 `destructive`，不会自动 apply。compact project status 保留决策信息；full drilldown 增加 7 天检索使用/忽略/误导/放弃/旧冲突排除统计，以及明确的 distill backlog 原因和基于 Agent 实际吞吐的保守清空估算。

<p align="center">
  <img src="docs/assets/harness-mem-lossless-session-flow.svg" alt="IDE 原始会话以不可变 revision 保存，全部有序 chunk 完成处理和末尾审查后才进入候选记忆" width="900" />
</p>

## 关键机制

Agent 可以自动处理低风险候选，但不能把风险、证据和变更原因藏起来；用户 review 的对象是 audit inbox，不是日常逐条写入闸门。

<p align="center">
  <img src="docs/assets/harness-mem-candidate-governance.svg" alt="candidate-before-truth 记忆治理状态机" width="900" />
</p>

运行时本身保持在后端位置：上层 Agent 走 MCP，底层是本地 canonical store、候选层、索引和审计。

<p align="center">
  <img src="docs/assets/harness-mem-runtime-layered-architecture.svg" alt="harness-mem runtime 分层架构" width="900" />
</p>

## 它解决什么

- 新 Agent 不必每次从零翻旧聊天。
- 长期项目里的决策、约定、handoff 和 review 结论可以被检索。
- 写入默认先进入 candidate layer，避免把猜测、噪声、临时结论变成真值。
- 同一套本地记忆后端可以接到 Claude Code、Codex、Cursor、Grok、Hermes、
  OpenCode、Antigravity 或其它 MCP-capable Agent。

## 安装

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.11 \
  harness-mem==0.9.11
```

`harness-mem` 本体通过 GitHub Releases 分发。上述命令会自动选择适用于
Windows、macOS 或 Linux 的原生 wheel，不需要 PyPI 项目或账号。

需要本地 vector / hybrid search 可选依赖：

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.11 \
  "harness-mem[hybrid]==0.9.11"
```

在当前设备一次性安装全部宿主的原生 Daily 命令。默认参数就是
`--client all --scope user`：

```bash
harness-mem integration commands sync
```

该命令只写各宿主的用户级 command、skill 或 workflow 目录，不安装项目
hooks，也不会把某个项目路径固化到全局命令中。

Claude Code 用户可以安装 repo-local plugin，并可选注册 MCP：

```powershell
git clone https://github.com/manhua-man/harness-mem.git
cd harness-mem
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

Cursor 请在项目 MCP 配置中使用 `harness-mem-mcp`，将 `cwd` 设为工作区，
并设置 `HARNESS_MEM_CLIENT=cursor`。首次 MCP 初始化会自动认领工作区、创建
project profile、安装匹配的项目 hooks，并幂等修复当前宿主的用户级命令；
不需要用户运行 hook installer，也不需要逐项目同步 command。完整配置
见 [MCP setup](docs/mcp-setup.md)。

需要显式修复时，七宿主统一使用
`harness-mem integration hooks sync --client all --project-root . --force`；
只修复一个宿主时，再把 `all` 换成对应宿主名。

仓库安装脚本会自动执行同一套“全部宿主、用户级”同步：

```powershell
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid
```

所有已支持宿主使用同一组动作：`status`、`wake`、`search`、`search-all`、
`distill`、`review`、`dream`。Claude Code 使用 `/hm:<action>`；Codex 使用可显式
调用的 `$hm-<action>` skill；Cursor、Grok、Hermes、OpenCode、Antigravity 使用
`/hm-<action>`。Codex 不支持注册自定义 slash command，因此 `$hm-*` 是它的原生命令形式。
用户级目录分别是：Claude Code `~/.claude/commands/hm`、Codex
`~/.codex/skills`、Cursor `~/.cursor/skills`、Grok `~/.grok/skills`、
Hermes `$HERMES_HOME/skills`（原生 Windows 默认为
`%LOCALAPPDATA%/hermes/skills`）、OpenCode `~/.config/opencode/commands`、
Antigravity `~/.gemini/antigravity/global_workflows`。
生成命令会按逻辑工具名解析当前 MCP namespace：直连 `harness_mem` 与通过
MCP Router 接入时，内部前缀可以不同，但用户入口不变。修改 MCP 注册或更新
工具 schema 后，需要重启对应 server 并新开 task，旧 task 不会热更新工具清单。

`codex-archive` 只是 Codex 历史归档会话的兼容 source identifier，不是第八个
宿主。旧配置和既有记录仍可读取，但 capability、status 和 qualification 统计
都会把它归入 Codex。

终端 CLI 是 operator console，不是日常 memory workflow。顶层只保留
`init`、`quickstart`/`qs`、`doctor`、`config`、`integration` 和
`maintenance`。导入和清理走 `harness-mem maintenance ...`，默认都是
dry-run 预览。
其它 CLI 维护动作只保留 operator repair / audit 所需的索引重建、storage
迁移/导出和状态审计。
procedural skill 生命周期治理不属于 public memory MCP 和 CLI 产品面。

## 仓库结构

- `harness_mem/`：runtime package。
- `plugins/harness-mem/`：Agent 客户端接入层。
- `tools/hm-distill/SKILL.md`：正式 MCP distill 主链的纯 Agent 指令；全部 runtime 实现统一位于 `harness_mem/`。
- `docs/quickstart.md`：最小启动路径。
- `docs/mcp-setup.md`：MCP client 接入说明。
- `docs/demo-cold-start.md`：可复现 cold-start demo。
- `docs/assets/`：logo 和公开 README 图。

## 文档

- [Quickstart](docs/quickstart.md)
- [MCP setup](docs/mcp-setup.md)
- [Cold-start demo](docs/demo-cold-start.md)
- [Recall audit contract](docs/recall-audit.md)
- [自动检索策略](docs/autopilot-search-policy.md)
- [Compatibility inventory](docs/compatibility-inventory.md)
- [参考项目证据目录](docs/reference-projects/index.md)
- [Roadmap](docs/roadmap.md)
- [Changelog](CHANGELOG.md)

## 开发检查

```bash
python -m compileall harness_mem
python -m ruff check harness_mem plugins tools
python -m mypy harness_mem
python -m pytest -q -m "not release_gate"  # PR 快速门
python -m pytest -q                        # 完整发布门
python -m harness_mem.cli --help
cargo test --workspace
```

快速门只跳过四个确定性的 60-case 穷举检索回放；全部断言仍会在 `main`
和正式 tag 的发布门中执行。

在声称运行中的产品已经完成前，使用跨项目 `outcome-verifier` Skill 执行
仓库的用户结果合同：

```bash
python tools/outcome-verifier/scripts/verify_outcomes.py \
  --config .codex/outcomes.json \
  --output .tmp/outcome-verifier/harness-mem-report.json
```

该只读探针要求：Codex 生命周期的 start/Stop 回执新鲜且成对、Dream 存在
持久化成功运行、最近完成的每个蒸馏会话都有有效语义摘要和可读 Note，以及
至少一条长期记忆能从 FTS read model 真正检索回来。只要 verdict 非零，就不能
因为代码、配置、队列或单元测试正常而声称用户结果已经落地。

发布标签会构建六个平台 wheel 和 sdist，在 Windows、macOS、Linux 上完成
全新安装验证，运行真实 sqlite-vec contract gate，并验证受支持的 Windows 升级
路径后再上传到 GitHub Release。本项目不发布到 PyPI。

当前包版本：**0.9.11**。它累计包含此前按 0.9.10 记录的增量上下文 lineage
工作；0.9.10 没有单独发布 package 或 tag。
