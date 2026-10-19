---
name: hm-distill
description: Internal extraction and assimilation contract for automatic session processing and source-verified memory review. Not a user-facing remember command.
---

# 内部会话整理合同

供自动 worker 及已有记忆/任务的审查纠正复用，完整读选中的会话，逐条留下以后有用的知识。用户无需发出“记住这次”或逐场选择整理；`hm` 人工入口只用于查阅和审查。目录不是来源处理的前提。

内部整理沿既有准备与收尾内核处理；人工纠正先由搜索返回旧条目，以 `target_knowledge` 准备当前纠正来源，再用 `finalize_session_distill(memory_points=[...], semantic_review=...)` 提交审查决定。`memory_points` 沿用以下证据和处置字段，项目/job/category/source 由运行时补齐。仅旧调用或已有候选才使用下述单点 suggest，不重复提交。不要为查看字段加载整表工具目录，也不要重复加载本规范。

## 正常路径

已知原生会话时，直接用 `prepare_session_distill(client=<宿主>, scope="all", session_id=<已知会话>)`，运行时选择并固定该来源，不先盘点全部设备。需要选择来源时才用 `inspect_sessions()`，把选择交给 `prepare_session_distill(scope="all", batch_sessions=...)`。在有工具执行环境时，完整盘点保留在执行环境，只向模型返回所选引用或必要摘要，不打印未选会话清单。直接完整读准备结果里的正文，不必再用文件或只读来源接口重复阅读。证据不足时才按返回的 exchange 或 chunk 位置补读。

对每个独立知识点，与准备结果的 `current_knowledge` 或已有 `search_memory` 结果比较，决定新增、确认、替换或不写。分类自然产生，不用固定模块表。来源明确说明、仍适用且影响后续选择的“未定／未知／未批准”也是当前状态，保留具体对象与适用范围；状态本身不列入 `unfinished_work`，只有来源要求继续执行的动作才作为待办。信息缺失、模型猜测或助手建议不能写成用户未定或未批准；有长期价值的助手方案可用 `source_report` 及原角色/序号/摘要保留具体建议身份，不变成用户决定。

没有长期价值的叙述不必逐句注册候选；已有候选的 `no_write` / `reject` 只结束该点，不把未经验证的说法提升为知识。完整来源审阅和引用完整性仍须核对。多个独立点可在一次工具执行中提交，再统一收尾；不要为每个点重复读取相同指令、准备正文或搜索结果。

用 `govern_memory(action="suggest", arguments=...)` 提交。正常字段为：

- `kind="memory"`，`project_name` 和 `distill_job_id` 使用准备结果，不要求用户提供。
- `content` 写一个独立事实；`canonical_title` 写具体标题，`topic_path` 为自然分类数组。
- 用户原话使用 `evidence_basis="user_statement"`、`verification_outcome="verified"`，引用为 `{"kind":"user_statement","exchange_index":<返回的序号>,"content_sha256":<返回的摘要>,"role":"user"}`。不要另造 `session_exchange` 类型。
- 文件证据用 `kind="repository"` 与真实文件路径、当前摘要；分块证据用 `kind="transcript"` 与返回的 `chunk_index`、摘要。
- `assimilation_disposition` 为 `add`、`confirm`、`refine`、`replace` 或 `no_write`，`assimilation_reason` 简述依据。其他未解决处置按工具支持的字段提交。

替换旧记忆用普通搜索原样返回的 `target_knowledge=[{title,statement,module,project_name}]`；只带已有的可用字段，不猜编号。`confirm` 可用旧正文精确匹配。单个点有问题时继续其他独立有效点，未完成工作交接保存。

更正时先搜索，用 `prepare_session_distill(client=<宿主>, session_id=<纠正会话>, target_knowledge=[<旧条目>])` 准备来源，旧条目原样来自搜索，由运行时确定归属。范围不匹配时保留来源，按同一旧条目重新准备并继续，不让用户管理项目或批准同项重试。明确更正优先原样保存用户给定的新措辞，只更新指出的内容，保留其余仍适用的条件、例外和未定状态，不为润色重写。

用 `finalize_session_distill` 收尾；`semantic_review` 包括 `session_summary`、`final_user_request`、`final_outcome`、`last_turn_status`、`contradictions`、`unfinished_work`、`evidence_status`、`promotion_decision`，准确描述会话，不把原会话的助手承诺当成已经保存。

收尾返回 `readback_verified=true` 时，运行时已重新核对当前 SQLite 与普通检索，直接复用完整的 `knowledge_changes`，不重复回读。无该标记、返回结果缺失或出现新冲突时，仍用普通搜索确认新说法存在、旧说法消失。多场用同一 `batch_id` 继续，失败先定位原因再恢复，不另建批次丢失进度或重复写入。

完整读完但没有长期价值内容时，以 `promotion_decision="no_promotion"` 明确收尾即可，不再要求填写额外的零候选问卷。

## 回复

从收尾结果的 `knowledge_changes` 直接展示实际保存的标题和正文；`not_written` 说明没有写的普通原因，`unfinished_work` 单独列出。没有变化就说没有变化，不拿测试、排队或 Agent 自报状态当成果。

日常输出不展开编号、摘要、回执和内部阶段。只有用户需要证据或详细审查时才展开。当前知识在 SQLite `knowledge_entries`，Note 和原始会话不是另一份知识库。

更细的取舍只在需要时读 [references/distillation-rules.md](references/distillation-rules.md)，不将整套材料当作每次必读内容。
