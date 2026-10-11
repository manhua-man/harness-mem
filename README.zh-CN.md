<p align="center">
  <img src="docs/assets/harness-mem-logo.svg" alt="harness-mem 标志" width="420" />
</p>

<h1 align="center">harness-mem</h1>

<p align="center"><strong>面向 AI Agent 的本机项目记忆。</strong></p>

<p align="center"><a href="README.md">English</a></p>

<p align="center">
  <a href="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml">
    <img src="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml/badge.svg" alt="公开 smoke 状态" />
  </a>
</p>

Agent 能读仓库，却不会自动保留前几次对话里重要的决定、约定和没做完的事。
`harness-mem` 在本机保存可复用的项目知识，让以后还能找回来，而不把你的工作流变成第二套知识管理软件。

未发布工作树的接入改进默认保留短会话。Cursor 覆盖导出的 JSONL 和已有隔离 fixture 的原生 SQLite 只读检查；这不代表支持所有真实数据库格式。来源文本为空、文件不可读和整理完成是不同状态。

未发布工作树的整理结果直接包含实际保存的知识，不只报告数量。在 `hm` 中说“看看现在记住了什么”，
即可按自然模块查看当前项目全部知识；普通搜索仍保持简短。

## 从这里开始

在 PowerShell、命令提示符或 Bash 中，直接复制这一整行安装 release：

```text
python -m pip install --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.28 harness-mem==0.9.28
```

你每使用一种 Agent，只需为它运行一次；不需要每个项目重复运行：

```bash
harness-mem quickstart
```

Quickstart 会识别当前应用。Codex 和 Claude Code 可以直接识别；无法识别时，
Quickstart 会停下来，请你运行一次例如
`harness-mem quickstart --client cursor` 的命令，而不会猜成另一个宿主。确认后它
只为该 Agent 安装一个 `$hm` 或 `/hm` 入口；它不检查项目、不写项目 Hook，也
不扫描或导入旧会话。它不会查看或修改 MCP 设置。Quickstart 确认入口已安装后，
新开一个 Agent 任务；如果已有 harness-mem 工具，就直接使用 `hm`。否则，交给管理现有
MCP 连接的 Agent、MCP Router、插件或用户已有的安装工具，按
[MCP 接入](docs/mcp-setup.md)连接；如果 Router 或插件已经提供了连接，不要再加第二条。
以后在任何项目直接使用 `hm`。每个项目第一次使用时会自动准备该项目和 Hook。软件通过 GitHub Releases
分发，不发布到 PyPI。

如需本地 vector 或 hybrid search，可从同一 release 索引安装
`"harness-mem[hybrid]==0.9.28"`。完整接入步骤与宿主例外见
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

统一入口会跟随你当前使用的语言，直接说明记住了什么、找到了什么，或需要如何纠正。
你不需要选择存储方式、模型连接或内部流程。

日常直接说普通话即可：不用了解内部程序，也不用填写、复制或管理记忆编号。
要纠正或删除时，描述记忆的标题或内容即可。Agent 在当前项目中查找目标，使用工具返回的引用并核对，不能猜编号。
自然文字无法唯一确定目标时，保留旧内容，用可读标题或内容说明无法确定哪条记忆。

一条失败或目标不明确，不应妨碍其他独立、已核实内容通过既有检查后保存。
回复必须分别说明实际保存了什么、什么还没完成，不能把部分保存说成全部完成。
项目不匹配、保存后无法读回等共同安全问题仍要求停止受影响的处理。

harness-mem 只保存当前有效记忆。纠错时直接替换旧内容，内容失效时直接删除；不保留
旧知识版本、知识归档副本、知识修改记录或撤销链。

新对话会自动加载相关内容。另行开启自动整理后，完成的对话会在后台通过你选择的 Agent 命令处理；如果它不可用，harness-mem 会直接说明，不会悄悄改用另一个。

## 不必每天面对的部分

未发布工作树新增只读会话清单、完整来源分页，以及按来源覆盖范围核对的 Agent 主题概览。
显式手工整理会冻结选定项目和来源 revision，形成可恢复的批次。整理由当前 Agent 执行，
独立于后台 CLI；批次完成不会自动删除来源。检查、准备与重试合同见
[MCP 接入](docs/mcp-setup.md#session-inspection-and-manual-batches-unreleased)。这些新增能力不包含在已发布的 `0.9.28` 安装包中。

终端 CLI 用于安装、诊断、集成修复和显式维护，不是日常找回记忆的流程。
`hm` 在执行用户请求前，只做一次简短的项目与 Hook 检查。出问题或操作员需要完整
诊断时，使用 `harness-mem doctor`；统计、版本、队列和修复证据不进入日常回复。
底层 MCP 工具、会话 Hook、后台整理、SQLite、来源检查和诊断仍然可用，但不再是“记住或找回工作”前必须学习的步骤。

当前开发版公开 20 个 MCP 工具，即原 19 个加上 `inspect_sessions`；自动 Dream 调度仍留在 Hook 和维护内部，不作为公开 MCP 工具。
自动检索只返回一份记忆；来源核验、中断恢复和检索反馈能力保留。

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

当前源码包版本：**0.9.28**。公开版本以 GitHub
[最新 Release](https://github.com/manhua-man/harness-mem/releases/latest) 为准。
