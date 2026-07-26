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

`harness-mem` 把这些内容变成本地记忆，通过单一 MCP memory surface 接给 Codex、Claude Code、Cursor、Gemini CLI 和其它 Agent 客户端。新 Agent 用 `wake` 和按任务触发的 `search` 找回上下文，用 `distill` 整理近期 evidence，低风险内容可自动提升为可读记忆；`review` 是事后审计、纠错和 undo 入口，`dream` 负责维护 ledger。

触发入口（用户级安装一次，之后所有项目可见）：

- `/hm:*` 命令：`status`、`wake`、`search`、`distill`、`review`、`dream`。
- Agent MCP 调用：自然语言、skill 或 hook 触发 `wake/search/distill/review`。
- Hook：会话开始注入 wake context；任务过程中按需 search；save point / 会话结束执行 retention。distill 活跃槽最多 2 条，按 3:1 recent/oldest 公平补位，带失败退避和每日新 job 上限；没有 Agent 时明确显示 `waiting_for_agent`，不会声称后台已完成语义处理。
- CLI：只做 setup、doctor、config、integration 和 maintenance。

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
| `distill` | 校验全部原始 chunk，读取不超过 3k token 的索引清单，选择完整语义窗口，再钻取候选级原文证据，最后做末尾审查、候选治理和 Dream。 |
| `review` | 事后审计、确认、拒绝、undo 或替代自动处理过的条目。 |
| `dream` | 维护 ledger、压缩过期状态，并在 save point / 会话结束后保留可回滚治理记录。 |

任务过程中的检索不是 always-on。PI 里的 `transformContext`、
`tool_result`、`prepareNextTurn`，Claude Code 的 `PostToolUse`，以及
Cursor 的 after-agent hook，都应映射到同一个 `autopilot_search_tick`
事件入口；`/hm:search` 只是客户端没有这类 hook 时的手动兜底。
`Stop` Hook 会保存不可变的原始 transcript revision，并排队它的全部有序 chunk。日常 `prepare_session_distill(evidence_mode="semantic", detail_level="compact", budget_tokens=3000)` 保留完整原文，由 runtime 校验并 checkpoint 每个 raw chunk，再返回包含全部 exchange 索引和风险信号的 compact manifest；Agent 先选择最多 8 个完整语义窗口，再只为候选主张钻取 raw proof。`detail_level="full"` 与兼容 `raw` 模式只用于显式完整审计，raw chunk 不截断内容。完成会话末尾审查后才可用稳定幂等 ID 生成候选，`finalize_session_distill` 随后执行 auto-review 和 Dream。`/hm:distill` 是同一条可恢复管线的立即执行入口。Hook 只负责同步、排队和注入 Agent 工作，不能声称没有 Agent 时已完成总结；没有原始 transcript 的旧 Observation 仅供审计，标记为 `legacy_partial`。

Observation 只是证据，不是被记住的事实。wake 的近期索引会明确标成“非事实证据”；L1/L2 只展示结构化当前事实和仍有效的 handoff。被当前仓库版本推翻的旧发布/版本说法会标记冲突，或从 truth/active 层移除。

隐私策略在落盘前执行：可用 `<private>...</private>` 包裹敏感片段，也可在项目 `.harness-mem.toml` 的 `[capture]` 中配置忽略 client、session 和 source glob；被排除内容不会进入 raw revision、chunk、Observation 或索引。`[transcript].retention_days` 控制自动保留期（`0` 表示永久保留）。`harness-mem maintenance erase --project NAME --session-id ID` 默认预览，增加 `--apply` 后会硬删除 raw revision、chunk、distill job、Observation、关联候选/事实以及 FTS/vector 索引。apply 会先持久化不含内容和原始标识的 receipt，再报告计划数、实际删除数和删除后验证；receipt 写入失败时不会开始删除，部分失败返回非零状态。

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
- 同一套本地记忆后端可以接到 Codex、Claude Code、Cursor、Gemini CLI 或其它 MCP-capable Agent。

## 安装

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.3 \
  harness-mem==0.9.3
```

`harness-mem` 本体通过 GitHub Releases 分发。上述命令会自动选择适用于
Windows、macOS 或 Linux 的原生 wheel，不需要 PyPI 项目或账号。

需要本地 vector / hybrid search 可选依赖：

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.3 \
  "harness-mem[hybrid]==0.9.3"
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
- `tools/session-distill/SKILL.md`：正式 MCP distill 主链的纯 Agent 指令；全部 runtime 实现统一位于 `harness_mem/`。
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
- [Changelog](CHANGELOG.md)

## 开发检查

```bash
python -m compileall harness_mem
python -m ruff check harness_mem plugins tools
python -m harness_mem.cli --help
cargo test --workspace
```

发布标签会构建六个平台 wheel 和 sdist，在 Windows、macOS、Linux 上完成
全新安装验证后上传到 GitHub Release。本项目不发布到 PyPI。

当前包版本：**0.9.3**。
