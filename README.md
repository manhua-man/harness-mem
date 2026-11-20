# harness-mem

换个项目、开一场新聊天，也能问起以前的决定。让当前 Agent 把已结束的讨论整理进本机知识库，以后可以直接问当时选了什么、为什么这样选、哪些条件下仍然适用。

| 用户可以这样说 | Agent 会做什么 |
| --- | --- |
| “把上次讨论建筑破坏的对话整理一下。” | **Distill** 找到对应会话，完整阅读，核对谁说了什么，告诉你保存了哪些知识、哪些问题仍待确认。中途暂停后可以接着读。 |
| “普通楼和特殊楼当时为什么要分开处理？” | **Search** 从当前知识中找回相关正文，用原先约定的条件回答。 |

## 跨项目和跨宿主使用

本地 Python 包 `harness_mem` 提供整理和检索能力。默认知识库位于当前用户的 `~/.harness-mem/data`，Search 默认跨项目读取。不同 Agent 或 Python 程序只要使用同一数据目录，就能检索同一份已整理的知识。

聊天里的 Agent 需要能发现随包提供的 [Distill](.agents/skills/distill/SKILL.md) 和 [Search](.agents/skills/search/SKILL.md)，并能调用安装了 `harness_mem` 的 Python。宿主支持用户级 Skill 路径时，接入一次即可在该宿主的各项目中使用。例如，Codex 可以从 `$CODEX_HOME/skills/` 加载两份 Skill。Agent 会结合提问和当前指令决定何时使用它们。

发起整理的 Agent 和产生原对话的工具可以不同。例如，在 Codex 中可以整理本机 Claude Code 的历史。可读取的原文格式由[会话适配器](harness_mem/adapters)决定。源码安装与开发入口见 [AGENTS.md](AGENTS.md)。

用户始终和当前 Agent 对话。会话正文、知识和检查点由本地运行时管理。两条工作流都无需后台语义模型。具体行为见 [整理](docs/features/distill.md) 和 [检索](docs/features/search.md)。
