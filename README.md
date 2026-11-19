# harness-mem

让当前 Agent 整理已结束的对话，在以后的任务里找回有用的知识。用户在对话里说出意图，Agent 负责读取、判断和答复，本地运行时负责来源、进度和保存。

| 用户可以这样说 | Agent 会做什么 |
| --- | --- |
| “把上次讨论建筑破坏的对话整理一下。” | **Distill** 找到对应会话，完整阅读，核对谁说了什么，告诉你保存了哪些知识、哪些问题仍待确认。中途暂停后可以接着读。 |
| “普通楼和特殊楼当时为什么要分开处理？” | **Search** 从当前知识中找回相关正文，用原先约定的条件回答。 |

## 宿主接入

本仓库提供两份原生 Agent Skill：[Distill](.agents/skills/distill/SKILL.md) 和 [Search](.agents/skills/search/SKILL.md)。在支持仓库级 `.agents/skills` 的宿主里，由宿主发现这两份指令。接入其他工作区时，让宿主加载同一份 Skill，并让其本地 Python 环境可导入 `harness_mem`。部署与开发入口见 [AGENTS.md](AGENTS.md)。

用户始终和当前 Agent 对话。会话正文、知识和检查点由本地运行时管理。两条工作流都无需后台语义模型。具体行为见 [整理](docs/features/distill.md) 和 [检索](docs/features/search.md)。
