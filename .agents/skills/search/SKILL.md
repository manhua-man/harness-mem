---
name: search
description: 从已整理的当前记忆中找回与用户问题相关的知识、约定和历史决定。
---

当用户问“上次是怎么决定的”“之前有没有记过”时，由当前 Agent 检索并直接回答。

1. 在宿主可用的 Python 环境里导入 `from harness_mem.search import search`，调用 `search(用户的问题)`。在本仓库使用已有开发环境。用户明确限定项目时才传 `scope="project", project_name=项目名`。
2. 读取返回的 `memories`。候选的 `read_cursor` 用同一查询、范围和上下文，传给 `search(..., detail="full", read_cursor=...)` 取回正文。分页沿用原查询以及 `continuation.arguments`。复合问题的匹配位置仅用于定位，逐项阅读正文后判断能否回答。
3. 用自然语言回答，指出具体证据缺口。如果结果为空，说明没有搜到；若状态为不可用，说明读取失败。用户无需执行命令、选择内部编号或转交工具输出。
