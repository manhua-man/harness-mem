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

`harness-mem` 把这些内容变成本地记忆，通过 MCP 接给 Codex、Claude Code、Cursor、Gemini CLI 和其它 Agent 客户端。新 Agent 用 `wake` 和 `search` 找回上下文，用 `distill` 提出新记忆；只有 review 通过的内容才会进入 confirmed memory。

<p align="center">
  <img src="docs/assets/harness-mem-cold-start-flow.svg" alt="新 Agent 通过 wake、search、distill、review 恢复跨会话项目上下文" width="900" />
</p>

## 主路径

```text
wake -> search -> distill -> review
```

| 步骤 | 作用 |
|---|---|
| `wake` | 从已确认记忆生成项目简报。 |
| `search` | 找回历史决策、规则和 handoff，并保留来源。 |
| `distill` | 把近期 session evidence 提炼成记忆候选，并预览审核建议。 |
| `review` | 确认、拒绝、替代或继续挂起候选。 |

## 关键机制

Agent 只能先提议，不能把旧会话噪声直接写成项目真值。

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
pip install git+https://github.com/manhua-man/harness-mem.git
```

需要本地 vector / hybrid search 可选依赖：

```bash
pip install "harness-mem[hybrid] @ git+https://github.com/manhua-man/harness-mem.git"
```

Claude Code 用户可以安装 repo-local plugin，并可选注册 MCP：

```powershell
git clone https://github.com/manhua-man/harness-mem.git
cd harness-mem
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

然后在 Agent 里使用：

```text
/hm:status
/hm:wake
/hm:search "release boundary"
/hm:distill <project> 10
/hm:review
```

终端 CLI 是 operator console，不是日常 memory workflow。顶层只保留
`init`、`quickstart`/`qs`、`doctor`、`config`、`integration` 和
`maintenance`；导入和清理走 `harness-mem maintenance ...`，默认都是 dry-run
预览。

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
- [Causal benchmark smoke](docs/causal-benchmark.md)
- [Changelog](CHANGELOG.md)

## 开发检查

```bash
python -m compileall harness_mem
python -m ruff check harness_mem plugins tools
python -m harness_mem.cli --help
cargo test --workspace
```

当前包版本：**0.8.2**。
