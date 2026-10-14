---
name: hm-distill
description: Process selected device sessions into readable current memory. Use when the user asks to remember, process, or continue sessions.
---

# 会话整理

完整读选中的会话，逐条留下以后有用的知识。目录不是前提；无需后台 CLI、项目初始化或 Hook 验收。

## 正常路径

需要选择来源时用 `inspect_sessions()`。把选择交给 `prepare_session_distill(scope="all", batch_sessions=...)`，运行时完整读取并固定来源。直接读准备结果里的正文，不必再调用只读来源接口重复阅读。证据不足时才按返回的 exchange 或 chunk 位置补读。

对每个独立知识点，与当前 `search_memory` 结果比较，决定新增、确认、替换或不写。分类自然产生，不用固定模块表。一场会话可以保存多条知识；一次性请求、未经确认的猜测和未完成任务不要混入当前记忆。

用 `govern_memory(action="suggest", arguments=...)` 提交。正常字段为：

- `kind="memory"`，`project_name` 和 `distill_job_id` 使用准备结果，不要求用户提供。
- `content` 写一个独立事实；`canonical_title` 写具体标题，`topic_path` 为自然分类数组。
- 用户原话使用 `evidence_basis="user_statement"`、`verification_outcome="verified"`，引用为 `{"kind":"user_statement","exchange_index":<返回的序号>,"content_sha256":<返回的摘要>,"role":"user"}`。不要另造 `session_exchange` 类型。
- 文件证据用 `kind="repository"` 与真实文件路径、当前摘要；分块证据用 `kind="transcript"` 与返回的 `chunk_index`、摘要。
- `assimilation_disposition` 为 `add`、`confirm`、`refine`、`replace` 或 `no_write`，`assimilation_reason` 简述依据。其他未解决处置按工具支持的字段提交。

替换旧记忆用普通搜索原样返回的 `target_knowledge=[{title,statement,module,project_name}]`；只带已有的可用字段，不猜编号。`confirm` 可用旧正文精确匹配。单个点有问题时继续其他独立有效点，未完成工作交接保存。

用 `finalize_session_distill` 收尾；`semantic_review` 包括 `session_summary`、`final_user_request`、`final_outcome`、`last_turn_status`、`contradictions`、`unfinished_work`、`evidence_status`、`promotion_decision`，准确描述会话，不把原会话的助手承诺当成已经保存。

然后普通搜索回读新增或替换的知识，确认新说法存在、旧说法消失。多场用同一 `batch_id` 继续，失败先定位原因再恢复，不另建批次丢失进度或重复写入。

完整读完但没有长期价值内容时，以 `promotion_decision="no_promotion"` 明确收尾即可，不再要求填写额外的零候选问卷。

## 回复

从收尾结果的 `knowledge_changes` 直接展示实际保存的标题和正文；`not_written` 说明没有写的普通原因，`unfinished_work` 单独列出。没有变化就说没有变化，不拿测试、排队或 Agent 自报状态当成果。

日常输出不展开编号、摘要、回执和内部阶段。只有用户需要证据或详细审查时才展开。当前知识在 SQLite `knowledge_entries`，Note 和原始会话不是另一份知识库。

更细的取舍只在需要时读 [references/distillation-rules.md](references/distillation-rules.md)，不将整套材料当作每次必读内容。
