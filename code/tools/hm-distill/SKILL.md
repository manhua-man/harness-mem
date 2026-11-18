---
name: hm-distill
description: Shared contract for Agent-led completed-session organization, source-verified memory updates and processed-history cleanup.
---

# 会话整理

这是各宿主 Agent 共用的记忆合同。当前 Agent 完整阅读、核验和归纳，运行时负责来源、版本、事务、回读与清理；不启动后台 CLI，不要求 Hook、Dream、`distill.autonomous.enabled` 或 `task_model_budget` 授权。不要把处理格式变成用户的工作。

## 读取完整来源

已知会话时，直接 `prepare_session_distill(client=<宿主>, scope="all", session_id=<会话>)`。需要选择时才 `inspect_sessions`，再把返回的选择交给 `prepare_session_distill(scope="all", batch_sessions=...)`；盘点保留在执行环境，不打印未选来源。

完整阅读准备结果的正文；不要再用文件或来源接口重复读相同内容。要求分块时读完每个无损 chunk，按返回的 lease/checkpoint 调用 `submit_distill_chunk`。仅缺证据、截断、冲突或来源变化时补读，不能以摘要替代完整来源。

准备结果有 `native_evidence.read` 时，缺少原生工具调用或执行结果就复制其中的调用按需读取；按返回的 `next_offset` 继续至空，筛选后的结果不代表完整来源。它与冻结版本绑定，筛选的是原生工具记录；工具文本仍可能嵌套目录或其他会话，不能因此当作本会话用户原话、当前实现事实或新增处理范围。不可用或版本变化须保留该证据缺口，不另猜原文路径。

多场复用同一 `batch_id`，保持冻结的来源、归属和 revision；续跑不纳入新会话。`archived_only=true` 只能选择可证的原生归档，归档状态变化时停止。用户暂停用 `pause=true`；明确继续后才用 `continue_batch=true`。`retry_failures=true` 只重试活动批次可重试的失败，不解除暂停或来源错误。

## 按问题归纳

一个会话可以产生零条、一条或多条记忆。每个独立知识点只表达一个独立事实：设想下一次遇到什么问题，这条结果单独读到时能否帮助做决定、找到入口、复用方法、避免已知错误或正确验收。不同问题各写一条，同一个答案合并，标题直接说结论。

`topic_path` 按当前任务写入项目的实际功能归类。每场准备及批次续跑都会带出 `current_module_catalog` 和含 `module` 的 `current_knowledge`。先对照条目用途，适用时逐段复用已有路径；只有独立的新功能才建模块或子主题。同一功能的不同作品、案例、宿主和批次沿用该功能路径，具体作品或案例名称放标题和正文。目录截断、对照不可用或匹配不足时，用普通检索按功能补查，再决定是否新增分类。目录与旧条目只供对照，写入归属仍以当前任务和已验证的纠正目标为准。

先保留会影响下次行动的结论、必要条件、例外、可复现的失败原因和后续纠正。会改错目标、误判通过、丢数据或重复踩坑的细节即使较长也要写清；历史节点、临时路径、单次测量和试错顺序只在解释本次结果有用时写进会话 Note（`semantic_review` 生成的整理笔记）。如果某次失败揭示了可复用的排查规则，就把规则单独写成记忆。

操作条目单独搜到就应能定位入口：保留已核对的完整路径，或明确仓库根与相对路径；列出影响实际操作的参数、默认是否写入、授权、精确目标清单及恢复条件。试用、正式应用与定向操作各自写清。验收条目保留需要发起的新请求、逐项通过条件、适用范围，以及现有证据只证明哪一层。泛称「目标域名」「按规则验收」不能代替来源已有的具体清单与断言。

技术结论核对当前代码、配置、文档、git 或执行证据。用户决定须有真实用户原话；宿主说明、工具消息和助手建议不冒充用户决定。旧实现或历史运行结果不能直接写成当前现状。

与 `current_knowledge` 及已完整返回的搜索结果对照；它只是有限相关结果，未命中不证明不存在。按主题补查必要目标，将同义说法合并，决定新增、确认、补充、替换或不写，不为换措辞重复保存。

来源明确说明、仍适用且影响后续选择的“未定／未知／未批准”也是当前状态，保留具体对象与适用范围；状态本身不列入 `unfinished_work`。信息缺失、模型猜测或助手建议不能写成用户未定或未批准；缺少回应只说明本次记录没有给出用户决定。

`source_report` 仅用于以后有用、已核对原文的具体方案或报告，保留说话人、时期、来源范围与方法细节；它不证明外部事实、当前实现、实际执行或用户批准。没有长期价值就留在会话总结或明确不写，不强迫每条助手回答入库。

正文直接写具体结论、必要日期、适用条件与方法；来源报告的会话时间、说话人和未独立核实边界由运行时统一展示，不手抄英文来源包装。不要因精简而省略历史结果的时间限制、例外或真正尚未验收的对象。

真正未完成的义务写入 `unfinished_work`，说清接手人要做什么、针对哪个对象、什么结果算完成，并带上必要的证据入口或前置条件。整理笔记记录当时发生了什么，交接记录帮助续做原任务；整理完成不代表原任务已执行。

## 一次提交判断

使用准备结果的 `finalize_contract.args_template`，按其 `instructions/required_fields/allowed_values` 填实际内容。模板不是事实；保留适用点，删除无关示例。一次调用 `finalize_session_distill(memory_points=[...], semantic_review=...)`，无需先逐点 suggest。

每点填写具体 `canonical_title`、`content`、`topic_path`、证据与 `assimilation_disposition`。证据引用复用准备值：用户为 `user_statement/user`，助手报告为 `source_report/assistant`；exchange 引用只含 `kind,exchange_index,content_sha256,role`，`exchange_index>=1`。文件或 chunk 证据按返回合同使用，不把 locator 混入 exchange。

每点的 `review` 是当前 Agent 对完整内容的一次判断：`support` 表示支持程度，`use` 表示以后用途，`reason` 说明依据；`conditions` 摘取最终正文中仍需保留的必要条件短语，`undecided_state` 为正文中的明确未定状态，无此内容才用 `[]`/`null`。写入须完整支持且长期有用；不确定或矛盾不能靠填 supported 变成通过。
写入或确认时用 `review.evidence` 逐项引用正文断言、每个条件和未定状态的原始证据。按从 1 开始的编号选取 `verification_refs` 内相应位置，摘录可唯一定位的原句。会话中填写该角色在对应 exchange 内的消息编号，文件引用直接摘录。先判断原文是否支持具体结论及其适用范围，再提交引用。
记录实际操作时用 `review.operations` 绑定正文原句、同一原生调用和返回。按准备合同区分只读检查、命令执行和直接交互。证据只有预览或界面绑定时，正文写明看到了什么及缺少哪个结果。核对工具指出的操作步骤、职责和过滤条件，保留会改变复用方式的顺序及范围。

纠正先搜索，以 `target_knowledge=[<旧条目>]` 准备当前纠正来源。旧条目原样来自搜索，由运行时确定归属；歧义或变化保留旧内容，不猜编号。`confirm/refine/replace` 各点把完整旧 `title/statement/project_name` 放入 `memory_points[i].target_knowledge`，仅已有 `module` 才带；新增点不带目标。准备的顶层目标不代替各点目标，收尾顶层不放目标。

`refine/replace` 检查全部旧目标，保留其余仍适用的条件、例外、证据、因果、权限、范围和未定状态，确认后填 `review.preserves_meaning=true`；报告替换还须确认同主题，填 `review.same_topic=true`。明确更正优先原样采用用户的新措辞，只改指出的内容；不让用户管理项目或批准同项重试。

运行时绑定最终正文、来源身份和目标版本。正常路径不重复提交 `final_scope_judgment`、分段证明、hash 或整套旧全文判断。已有高级 final_scope、报告拆分或 `govern_memory(action="decide")` 的兼容任务才按需查该工具真实 schema，不与 `memory_points[i].review` 混用；已有 suggest 不重复提交，distill job 统一 finalize。

`semantic_review` 按模板写原会话的总结、最后请求、实际结果、状态、矛盾和未完成动作；不写本次整理的阶段日志。`contradictions`/`unfinished_work` 为字符串数组，后者仅真实动作。无长期价值用 `no_promotion` 收尾；只有原任务待办可用 `partial` 加具体交接，不虚构知识或额外零候选问卷。

## 回读、清理与回复

`readback_verified=true` 表示运行时已核对 SQLite 与普通检索；直接复用完整 `knowledge_changes`，不重复搜索。缺标记、结果缺失或出现新冲突时，再确认新内容存在、被替换旧内容消失。重试复用原批次、已提交结果和回读，不能用新计划覆盖已完成任务。

用户明确要求清理后，以原 `batch_id` 加 `cleanup_processed=true` 预览，核对范围后加 `apply_cleanup=true` 执行；已有同范围授权不重复询问。不重新选源、不重新整理、不启用后台。原项目任务未完成不自动阻止清理，必要义务须在最终 Note 和可独立接续的交接中保存并回读。

未读来源、待补判断、未解决候选、证据仍依赖将删材料、活跃或变更来源、回读失败均保留并说明。保留最终 Note 与必要交接；共享数据库不能为一个会话整库删除。知识已保存、原文已删除分别报告。

从 `knowledge_changes` 展示实际标题和正文；`not_written` 用普通话说明原因，`unfinished_work` 单独列出。不写不证明完成；失败保留来源，说明可接续步骤，不隐瞒失败或另建知识库。日常输出不展开编号、摘要、回执和内部阶段。

当前知识的真源是 SQLite `knowledge_entries`，Note 和原始会话不是另一份知识库。更细取舍按需读 [distillation-rules.md](references/distillation-rules.md)，不把整套参考材料变成每次必读。
