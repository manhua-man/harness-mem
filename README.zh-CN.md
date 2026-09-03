<p align="center">
  <img src="docs/assets/harness-mem-logo.svg" alt="harness-mem 标志" width="420" />
</p>

<h1 align="center">harness-mem</h1>

<p align="center"><strong>面向 AI Agent 的本地优先、可审计项目记忆。</strong></p>

<p align="center"><a href="README.md">English</a></p>

<p align="center">
  <a href="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml">
    <img src="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml/badge.svg" alt="公开 smoke 状态" />
  </a>
</p>

Agent 能读仓库，却不会自动保留过去十场会话里的决定、约定、handoff 或尚未验证的事项。
`harness-mem` 在本机保存可复用的项目知识，让下一次 task 能找回来，而不把你的工作流变成第二套知识管理软件。

## 从这里开始

安装 release：

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.26 \
  harness-mem==0.9.26
```

然后在你使用的 Agent 应用里全局运行一次：

```bash
harness-mem quickstart
```

Quickstart 会识别当前应用。Codex 和 Claude Code 可以直接识别；无法识别时，
Quickstart 会停下来，请你运行一次例如
`harness-mem quickstart --client cursor` 的命令，而不会猜成另一个宿主。确认后它
只为该应用安装一个全局 `$hm` 或 `/hm` 入口；它不检查项目、不写项目 Hook，也
不扫描或导入旧会话。它不会查看或修改 MCP 设置。MCP 连接由 Agent、MCP Router、插件或用户已有的安装工具管理。如果 Agent
还不能使用 harness-mem，再单独按
[MCP 接入](docs/mcp-setup.md)连接。完成后新开一个 task，以后在任何项目直接使用
`hm`。每个项目第一次使用时会自动准备该项目和 Hook。软件通过 GitHub Releases
分发，不发布到 PyPI。

如需本地 vector 或 hybrid search，可从同一 release 索引安装
`"harness-mem[hybrid]==0.9.26"`。完整接入步骤与宿主例外见
[Quickstart](docs/quickstart.md)。

## 日常只用一个入口

在 Agent 中使用一个入口：

| 宿主 | 入口 |
|---|---|
| Codex | `$hm` |
| Claude Code、Cursor、Grok、Hermes、OpenCode、Antigravity | `/hm` |

然后直接说你想做什么：

```text
记住这次。
找一下以前怎么做的。
这条记忆不对。
```

统一入口会选择所需的记忆操作，并用普通话说明：记住了什么、找到了什么，或需要如何纠正。
你不需要选择存储、provider profile 或内部工作流。

新会话会自动加载相关上下文。另行授权自动整理后，完成的会话会在后台通过所选宿主 CLI 处理；处理期间可以继续工作。后台不会悄悄替换成别的宿主 CLI。

## 不必每天面对的部分

终端 CLI 用于安装、诊断、集成修复和显式维护，不是日常找回记忆的流程。
`status`、Doctor 和 maintenance 只在出问题，或操作员需要检查、修复系统时使用。
底层 MCP 工具、会话 Hook、后台治理、SQLite、证据检查和审计记录仍然可用，但不再是“记住或找回工作”前必须学习的步骤。

项目记忆默认保留在本机。长期知识变更前会检查证据；不确定或不安全的来源清理始终需要显式授权。
在敏感项目开启自动处理前，请阅读[后台记忆策略](docs/background-memory.md)；执行任何破坏性维护前，请阅读 [Quickstart 的隐私与清理说明](docs/quickstart.md#advanced-and-repair)。

## 需要时再看详情

- [Quickstart](docs/quickstart.md)：接入、原生宿主说明与恢复方法。
- [MCP setup](docs/mcp-setup.md)：手动或非标准 Agent 连接。
- [Cold-start demo](docs/demo-cold-start.md)：可复现的检索演示。
- [IDE hook adapter matrix](docs/ide-hook-adapter-matrix.md)：支持宿主的能力与安装证据。
- [记忆采用合同](docs/memory-adoption.md)：提取、验证、归纳吸收与检索的设计。
- [Roadmap](docs/roadmap.md) 与 [Changelog](CHANGELOG.md)：发布与计划工作。

## 贡献者

runtime 代码位于 `harness_mem/`；`code/plugins/harness-mem/` 是 Agent 接入资产；
`code/tools/hm-distill/SKILL.md` 是纯指令手册，不是第二套 runtime。

贡献前运行相关检查：

```bash
python -m compileall harness_mem
python -m ruff check harness_mem code/plugins code/tools
python -m mypy harness_mem
python -m pytest -q -m "not release_gate"
python -m pytest -q
python -m harness_mem.cli --help
cargo test --workspace
```

用户可见运行结果的验收命令：

```bash
python code/tools/outcome-verifier/scripts/verify_outcomes.py \
  --config .codex/outcomes.json \
  --output .tmp/outcome-verifier/harness-mem-report.json
```

当前源码包版本：**0.9.26**。GitHub 最新公开 Release：**0.9.26**。
