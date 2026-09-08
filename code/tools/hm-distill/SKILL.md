---
name: hm-distill
description: Process project sessions into readable current memory. Use when the user asks to remember, process, or continue sessions.
---

# HM Distill

这是 `hm` 背后的整理规则，不是用户要学习的命令清单。读完整会话，留下以后有用的项目知识；没有价值的内容不写入。

## 处理

1. 用 `prepare_session_distill` 取得当前项目的完整会话材料。明确指定会话时只处理那一场；未指定时处理当前项目范围内匹配的内容。不要读取其他项目，也不要人为加入每场、每批或每天的数量限制。
2. 完整阅读来源。把一场会话拆成彼此独立的知识点；一场会话可以产生多条记忆，也可以一条都不产生。必要时用语义或原文读取补足证据；原文不完整就不要假装完整。
3. 每个知识点分别核对：来源是否真的支持、当前代码或用户决定是否仍有效、当前记忆是否已有同一事实。然后分别决定新增、替换、删除或不写；未完成的工作单独交接，不当作记忆。
4. 通过现有 `govern_memory` 写入决定，通过 `finalize_session_distill` 收尾。不要创建第二套写入流程。写入前必须带证据；运行时会再次检查证据和目标。没有明确决定时保持未完成。
5. `finalize_session_distill` 完成后，用普通 `search_memory` 读回新增或替换内容；新说法找不到，或旧说法仍能找到，就不能报告成功。

收尾时提交完整的 `semantic_review`（至少包括 `session_summary`、`final_user_request`、`final_outcome`、`last_turn_status`、`contradictions`、`unfinished_work`、`evidence_status` 和 `promotion_decision`），再读取运行结果里的已保存内容。这些是内部数据，不要原样展示给用户，也不要把 Agent 自报的状态当成事实。

## 最低可靠性要求

写入前只问五件事：以后是否还会用、范围是否清楚、内容是否足够窄、证据是否完整、是否与当前记忆重复或冲突。先补齐证据再决定；通过后才写，否则不写或留待处理。只有本机核对通过的内容才能写入。

- 需要分块读取时，按 `prepare_session_distill` 返回的顺序逐块调用 `submit_distill_chunk`，直到进入可收尾状态。
- 每个候选都要有 `evidence_basis`、`verification_outcome` 和 `verification_refs`；`ANSWERED` 只表示证据问题已回答，不等于一定要写入。
- 只把一个独立、可复用的结论写成一条清楚的事实。运行结果只是内部提交结果，不要复制 Agent 自报的状态。
- `add`、`refine`、`replace` 只写一条清楚的当前事实；替换会删除旧当前条目。不要把来源、候选、回执或 Note 当作当前记忆。
- 只有当前项目的 `knowledge_entries` 是长期记忆；旧兼容行、临时材料和原始会话不能进入普通记忆搜索。
- 失败、证据不足或来源不完整时保留会话并说明原因；不要把排队、接口返回或测试通过说成用户结果。

## 结果

默认只报告实际知识变化：

```text
记住了：<新增、替换或删除的内容；没有则写“没有需要长期记住的内容”>
没记：<没有写入的普通原因；没有则省略>
还没完成：<未完成事项；没有则省略>
```

不要默认输出会话总数、任务状态、进度、费用、内部编号或对应表。写入、修改和交接由现有工具在内部完成，不要把它们变成用户要学习的步骤。只有用户明确要完整审查时，才展开“会话 → 主题 → 知识 → 实际证据”。`Session Note` 是可读摘要，不是另一份记忆。可读结果不要附加会话、任务、来源或内部编号。

用户主动整理成功后，按运行时返回的结果清理该会话原文、对应宿主历史和生成摘要；不制作会话备份，也不清空宿主全部历史。Dream 自动整理只归档，失败或未完成的来源保留。

如果 MCP 不可用，直接说明当前入口无法使用和最短恢复动作；不要改走终端或另一套记忆库。

详细的分类和证据取舍见 [references/distillation-rules.md](references/distillation-rules.md)。不要把这些内部规则复述给用户，除非用户明确要求查看处理方法。
