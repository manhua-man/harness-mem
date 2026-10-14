<p align="center">
  <img src="docs/assets/harness-mem-logo.svg" alt="harness-mem 标志" width="420" />
</p>

<h1 align="center">harness-mem</h1>

<p align="center"><strong>面向 AI Agent 的本机记忆引擎。</strong></p>

<p align="center"><a href="README.md">English</a></p>

<p align="center">
  <a href="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml">
    <img src="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml/badge.svg" alt="公开 smoke 状态" />
  </a>
</p>

Agent 能读仓库，却不会自动保留前几次对话里重要的决定、约定和没做完的事。
`harness-mem` 从会话中保存以后有用的知识，让 Agent 能找回并纠正记忆，不要求你管理项目或目录。

未发布工作树支持从设备会话列表中选定范围，连续整理不同目录、无目录和已删除目录的会话。
目录仅是背景线索；逐条验证、SQLite 保存和普通搜索回读仍然必需。安装不会自动整理旧会话。

未发布工作树的接入改进默认保留短会话。Cursor 覆盖导出的 JSONL 和已有隔离 fixture 的原生 SQLite 只读检查；这不代表支持所有真实数据库格式。来源文本为空、文件不可读和整理完成是不同状态。

未发布工作树的整理结果直接包含实际保存的知识，不只报告数量。在 `hm` 中说“看看现在记住了什么”，
即可查看当前知识；普通搜索仍保持简短。也可明确要求只看某个项目，并按自然模块展示。

未发布的读取改进会直接返回短知识，结果多时由 Agent 按返回位置继续读；用户要查看全部时，
Agent 读完所有页。长条目可以完整展开。启动时还没有任务就先提示记忆可用，知道任务后再找
相关知识。输出大小使用现有 wake/search 设置，按完整返回内容计算，也包括自动检索的反馈字段。

用户已批准的未发布默认行为是跨**全部项目**找回记忆：普通搜索、会话开始的 `wake`
和任务中的自动检索都读取 SQLite 当前知识，不锁定活动工作区。项目信息只作可选上下文
或明确筛选条件；原始对话、job 材料和 legacy 行仍不进入记忆检索。2026-10-12 已核对当前源码及实际 MCP 的盘点、搜索和 wake；已发布 `0.9.28` 不包含这项默认行为变更。

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
以后直接使用 `hm`，不要求为搜索或整理设备会话建立项目。需要当前工作区的自动 Hook 时才准备该工作区。软件通过 GitHub Releases
分发，不发布到 PyPI。

七个已支持宿主始终都在产品范围内，并非只面向 Codex。未发布的 Hook
补修增加 Claude Code／Cursor 原生事件注册，并让 Claude Code、Cursor、Grok
和 OpenCode 传递原生会话编号。依赖要求与隔离测试、真实应用证据的区别见
[宿主接入表](docs/ide-hook-adapter-matrix.md)。

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
要纠正或删除时，描述记忆的标题或内容即可。Agent 从当前记忆中查找目标，修改前核对其保存的上下文和工具返回的引用，不能猜编号。
自然文字无法唯一确定目标时，保留旧内容，用可读标题或内容说明无法确定哪条记忆。

一条失败或目标不明确，不应妨碍其他独立、已核实内容通过既有检查后保存。
回复必须分别说明实际保存了什么、什么还没完成，不能把部分保存说成全部完成。
项目不匹配、保存后无法读回等共同安全问题仍要求停止受影响的处理。

harness-mem 只保存当前有效记忆。纠错时直接替换旧内容，内容失效时直接删除；不保留
旧知识版本、知识归档副本、知识修改记录或撤销链。

新对话会自动加载相关内容。另行开启自动整理后，完成的对话会在后台通过你选择的 Agent 命令处理；如果它不可用，harness-mem 会直接说明，不会悄悄改用另一个。

## 不必每天面对的部分

未发布工作树新增只读会话清单、完整来源分页，以及按来源覆盖范围核对的 Agent 主题概览。
Agent 从宿主原生任务上下文确定调用者工作区，不使用 MCP Router 的工作目录。
自动发现先调用 `inspect_sessions {}`，仅返回项目元数据摘要与会话数量，覆盖 Claude Code、
Codex、Cursor、Grok、Hermes、OpenCode 和 Antigravity 七个原生 adapter。
Agent 在内部使用返回的来源信息检查用户指定范围，无需用户填写目录或编号。
项目 profile 只是可选上下文标签，不拥有目录或名称的裁决权。会话记录中的旧目录
不占用项目名称，也不强制改名；同 basename 的不同根目录可以使用同一标签，
但选定会话和冻结批次仍分别核对文件及来源。用户不需要管理目录搬迁、退役或名称占用。
发现本身不导入旧会话，也不开启后台。

显式手工整理会独立重新核验选定完整来源，再冻结选定会话范围和来源 revision，形成可恢复的批次。
恢复时从冻结批次确定范围，不让用户重填目录或编号，也不纳入新发现的会话。整理由当前 Agent 执行，
独立于后台 CLI；批次完成不会自动删除来源。检查、准备与重试合同见
[MCP 接入](docs/mcp-setup.md#session-inspection-and-manual-batches-unreleased)。这些新增能力不包含在已发布的 `0.9.28` 安装包中。

自动项目探针以确定性的 Agent 决定运行实际 MCP dispatcher、原生格式、SQLite、Note 与普通搜索链路。
当前源码通过 772 项定向回归及五项隔离结果检查，实际 MCP 的盘点、普通搜索和 wake 另行核对。
隔离结果不证明七个真实应用、模型或 Hook 已运行。本轮按不改用户目录的要求，未同步全局宿主入口说明。

终端 CLI 用于安装、诊断、集成修复和显式维护，不是日常找回记忆的流程。
普通搜索和人工整理不要求先建项目或安装 Hook；需要自动记录时才准备当前工作区。出问题或操作员需要完整
诊断时，使用 `harness-mem doctor`；统计、版本、队列和修复证据不进入日常回复。
底层 MCP 工具、会话 Hook、后台整理、SQLite、来源检查和诊断仍然可用，但不再是“记住或找回工作”前必须学习的步骤。

当前开发版公开 20 个 MCP 工具，即原 19 个加上 `inspect_sessions`；自动 Dream 调度仍留在 Hook 和维护内部，不作为公开 MCP 工具。
自动检索只返回一份记忆；来源核验、中断恢复和检索反馈能力保留。
SQLite 已有 `project_name` 字段保留以兼容旧数据，本次不迁移或重新分类真实记忆。
默认跨项目检索不会放宽来源访问权限；选定范围内的完整来源和文件核验仍须通过。

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
