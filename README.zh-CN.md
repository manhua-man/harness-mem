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

触发入口：

- `/hm:*` 命令：`status`、`wake`、`search`、`distill`、`review`、`dream`。
- Agent MCP 调用：自然语言、skill 或 hook 触发 `wake/search/distill/review`。
- Hook：会话开始注入 wake context；任务过程中按需 search；save point / 会话结束只同步 transcript evidence 并创建待蒸馏任务。
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
| `distill` | 把近期 session evidence 走成 packet / candidate 流程，然后运行共享 auto-review 策略。 |
| `review` | 事后审计、确认、拒绝、undo 或替代自动处理过的条目。 |
| `dream` | 维护 ledger、压缩过期状态，并在 save point / 会话结束后保留可回滚治理记录。 |

任务过程中的检索不是 always-on。PI 里的 `transformContext`、
`tool_result`、`prepareNextTurn`，Claude Code 的 `PostToolUse`，以及
Cursor 的 after-agent hook，都应映射到同一个 `autopilot_search_tick`
事件入口；`/hm:search` 只是客户端没有这类 hook 时的手动兜底。
`prepare_session_distill` 只负责同步和打包证据，不会自己合成候选真值。下一个可运行的 Agent 会消费待蒸馏任务，生成候选并调用 `auto_review_candidates(apply=true)`；该提交点完成任务并触发 Dream。`/hm:distill` 是同一管线的立即执行入口。

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
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.8.23.3 \
  harness-mem==0.8.23.3
```

`harness-mem` 本体通过 GitHub Releases 分发。上述命令会自动选择适用于
Windows、macOS 或 Linux 的原生 wheel，不需要 PyPI 项目或账号。

需要本地 vector / hybrid search 可选依赖：

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.8.23.3 \
  "harness-mem[hybrid]==0.8.23.3"
```

Claude Code 用户可以安装 repo-local plugin，并可选注册 MCP：

```powershell
git clone https://github.com/manhua-man/harness-mem.git
cd harness-mem
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

如果要一次性安装 IDE hooks，可以运行：

```bash
harness-mem integration install-hook-suite --client cursor
harness-mem integration install-hook-suite --client claude-code
```

然后在 Agent 里使用：

```text
/hm:status
/hm:wake
/hm:search "release boundary"
/hm:distill <project> 10
/hm:review
/hm:dream
```

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
- `tools/session-distill/`：session distillation 参考 skill。
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

当前包版本：**0.8.23.3**。
