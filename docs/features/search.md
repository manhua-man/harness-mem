# Search · 找回当前知识

用户可以直接问“我们之前怎么决定的？”当前 Agent 用用户的问题检索，默认跨项目。只有用户指定项目范围时才缩小读取范围。

一次请求读取相应的当前知识，按相关性排序并折叠重复结果。遇到复合问题时，排序和分问提示共用同一次拆问。结果较长时，Agent 按返回的位置继续读取完整正文。分问指向的结果仍需要核对适用条件；没有正文支持的部分在答复中标明。

调用方式和分页规则见 [Search Skill](../../.agents/skills/search/SKILL.md)。覆盖范围见 [跨项目读取测试](../../code/tests/test_global_memory_defaults.py) 和 [匹配与排序测试](../../code/tests/test_current_knowledge_relevance.py)。
