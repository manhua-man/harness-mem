# harness-mem

本地 Agent 记忆工具。用 **Distill** 从已结束的对话里提取有来源的知识，用 **Search** 在新任务里找回当前仍适用的内容。两者通过同一个 MCP 服务工作，手工整理可以独立运行。

## 从源码开始

当前源码版本是 **0.0.1**。准备 Python 3.9 或更高版本、Rust 工具链和本机编译器，在仓库根目录、目标 Python 虚拟环境中运行：

```sh
python -m pip install .
harness-mem --help
```

在 Agent 中连接这个环境的服务进程，配置示例见 [MCP setup](docs/mcp-setup.md)。连接后可以直接问「有哪些已结束的会话可以整理？」或「我们之前怎么决定这个问题的？」。

## 功能入口

| 想做的事 | 从哪里开始 |
| --- | --- |
| 盘点会话、整理一批历史、检查写入结果或清理已处理的原文 | [Distill](docs/features/distill.md) |
| 跨项目找知识、逐项回答复合问题、在新任务中唤起相关记忆 | [Search](docs/features/search.md) |
| 接入宿主生命周期、授权后台处理或诊断连接 | [宿主接入](docs/quickstart.md) |

开发入口见 [AGENTS.md](AGENTS.md)，协作和验收约定见 [CLAUDE.md](CLAUDE.md)，面向用户的响应设计见 [DESIGN.md](DESIGN.md)。
