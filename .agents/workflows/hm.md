---
name: "HM"
description: 整理已结束会话、清理已处理历史、找回和纠正知识
category: Memory
tags: [harness-mem, memory]
wireFormatVersion: hm-wire-v3.5
---

`hm` 是所有受支持宿主共用的记忆入口：当前 Agent 把完整会话归纳为以后有用的知识，按用户要求清理已处理历史，再在任务中召回。检索和人工整理无需项目初始化、Hook、后台 CLI 或 Dream；不要求用户管理编号、目录或逐条审批，不自设每日／批次数量上限。

## Command 入口

Codex 用 `$hm <action> [参数]`，其他宿主用 `/hm <action> [参数]`。这是同一个 Agent command，调用已有 MCP，不新增终端 CLI。

| Command 参数 | 动作 |
| --- | --- |
| `help`，或不带参数 | 只显示本表和示例，不调用工具。 |
| `status [--project <名称>]` | `inspect_sessions` 只读查看历史、批次进度和待办，不安装或初始化。 |
| `distill --project <名称> [--archived-only] [--cleanup]` 或 `distill --all [--archived-only] [--cleanup]` | 完整整理选中已结束会话；归档筛选传 `archived_only=true`；`--cleanup` 授权成功保存与回读后清理同一选择。 |
| `clean [--project <名称>] [--apply]` | 复用已完成批次；默认仅预览，`--apply` 才执行该范围的清理。 |
| `search "<主题>" [--project-only <名称>]` | 默认跨全部项目检索；只有 `--project-only` 才筛选项目。 |
| `review ["<标题或主题>"]` | 只读审查当前知识；无主题时从模块和第一页开始，不自动改写。 |
| `review --replace "<旧标题或正文>" --with "<新正文>" [--project <名称>]` | 搜索旧项和来源，经共同核验、写入流程纠正。 |
| `review --delete "<旧标题或正文>" [--project <名称>]` | 查明唯一现存目标后按明确授权删除，不扩大范围。 |
| `pause [--project <名称>]` / `continue [--project <名称>]` | 暂停／继续原冻结批次，不换源或扩范围。 |

操作词和参数名固定，双引号内保留原文。缺少必需参数、未知操作／参数、`--project` 与 `--all` 冲突、`--with` 不匹配 `--replace` 时显示用法，不猜测执行。裸 `distill` 只提示选择范围；`search` 不接受隐含项目筛选。例：`$hm distill --project oiioii-studio --cleanup`；`$hm search "上游模型与本地替代"`；`$hm clean --project oiioii-studio --apply`。

`clean/pause/continue` 未指定项目时，复用当前已选批次或盘点中唯一匹配项；歧义用可读范围让用户选择，不索要 ID。MCP 未接通就说明缺失，不自动安装、启用 Hook 或恢复连接。

## 整理与纠正

已知会话直接 `prepare_session_distill(client=<宿主>, scope="all", session_id=<会话>)`；需要选择才 `inspect_sessions`，把所选引用交给 `prepare_session_distill(scope="all", batch_sessions=...)`。全设备批次可以跨项目选择，新任务在完整读取原生来源后沿用可唯一确认的原项目绑定。完整读准备正文，分块时读完所有 chunk 并按返回合同提交；不重复打印全设备清单、重读未变来源或用摘要替代原文。多场用同一 `batch_id`，每场以准备结果的写入项目、当前模块和记忆对照为准。

一场会话可以有多条独立记忆。每条回答一个以后会问的问题，保留能指导决定、找到入口、复用方法、避免重复失败或正确验收的具体结论，以及必要条件、例外、失败原因和后续纠正。入口须能定位，影响结果的参数、精确目标、写入与恢复条件、逐项验收一并保留。一次性环境值或试错经过按需留在会话整理笔记。技术现状核对当前代码或执行证据；与 `current_knowledge` 和已有搜索全文对照，同义合并，逐点新增、确认、补充、替换或不写。`topic_path` 复用原项目已有功能路径；作品和案例放在标题和正文，只有独立的新功能才加分类。提交前把同类条目并排检查重复与缺失条件。

明确、仍适用且影响后续选择的未定／未知／未批准，按对象和范围保留为当前状态，不放进 `unfinished_work`；缺信息、猜测、建议或缺少用户回应不能推断用户状态。只有来源要求继续执行的真实动作、证据保留、回滚和交付前置条件进入交接。

以后有用的具体助手方案才用 `source_report` 保留说话人、时期、来源范围及方法细节；不升为外部事实、当前执行或用户批准。用户原话用 `user_statement`，宿主说明不当用户决定。无长期价值的报告留在总结或不写，不强制入库。

已按现行文件核实的事实用 `repository` 证据，当前项目用相对路径，用户配置的 `evidence.repository_roots` 内其他维护源用绝对路径。引用必须对应已检查的文件及其 SHA-256。跨目录来源不改变知识归属。

按 `finalize_contract.instructions/required_fields/allowed_values` 填 `args_template`，一次 `finalize_session_distill(memory_points=[...], semantic_review=...)` 保存。模板不是事实，删除无关示例；各点 `review` 填 `support/use/reason/conditions/undecided_state`。条件取最终正文的必要短语；没有必要条件用空数组，没有来源明确的未定状态用 null，不重复填分段证明、hash 和旧全文判断。
起草前读完整会话与 `native_evidence.review_questions` 各页，用 `native_evidence.read` 查原始调用和返回。补查输入校验、失败处理及适用条件。用 `review.evidence` 为断言、条件和未定状态引用确切消息或文件。用 `review.operations` 绑定原生证据与正文，读取代码或历史回执用 `inspection`。核对当次动作、返回结果和后续更正后再写「实际完成」。保存后逐项对照 `knowledge_changes` 全文。

若工具返回 `source_conditions_need_review`，回查它指出的会话或文件位置。会影响复用和决策的条件补进正文及 `review.conditions`。已失效、仅限当次或与该知识无关的条件，用 `condition_exclusions` 按返回的 ID 写明原因，再收尾同一个 job。

纠正先搜索，原样 `target_knowledge=[<旧条目>]` 准备当前来源；确认／补充／替换各点将完整旧 `title/statement/project_name` 放在 `memory_points[i].target_knowledge`，已有 `module` 才带。准备顶层目标只绑定来源与归属，不代各点目标；收尾顶层不放目标。运行时唯一匹配和检查旧版本，歧义保留旧内容，不猜编号。

`refine/replace` 保留旧目标仍适用的证据、因果、条件、例外、权限、范围和未定状态，核对后填 `review.preserves_meaning=true`；报告替换另需 `review.same_topic=true`。明确更正优先原样用新措辞，只改指出内容，不让用户管理项目或批准同项重试。

证据复用准备值：exchange 只含 `kind,exchange_index,content_sha256,role`，`exchange_index>=1`；用户为 `user_statement/user`，助手为 `source_report/assistant`，文件/chunk 证据另按合同。`semantic_review` 总结原会话，矛盾和未完成为字符串数组；无长期价值正常 `no_promotion`，只有原任务待办用 `partial` 加真实交接。

完整取舍按需读内部 `hm-distill`。正常 `memory_points[i].review` 不与旧 `final_scope_judgment` 混用；已有高级 final_scope、报告拆分或 `govern_memory(action="decide")` 任务才按需查真实 schema。已有 suggest 不重复提交，distill job 统一 finalize；来源、事务、版本和回读仍由共同运行时负责。

## 检索与调用

`search_memory` 默认 `scope="all"`，包含 global，任务项目不筛选；仅用户明确限制才用 `scope="project"`，误限取消，明确范围不扩大。回忆用当前知识，技术现状仍核真源。完整 `statement`、未变来源和 `wake/context_injection` 已有全文直接复用；只在缺答、冲突、源变或截断时补查，不限必要检索次数，不机械换词重复查。

默认 `detail="auto"`，复合问题用原问首查。按 `question_parts` 核对每项条件和结果，`question_part_matches` 仅提示可先看的正文。已有全文直接回答，缺哪项只补查哪项并标明仍缺的证据。预览用原 query/scope/task_context 与 `read_cursor`、`detail="full"` 打开。按 `continuation.arguments` 和 `reuse_arguments` 续读，查看全部须读完页。`task_context` 可传背景和排除项，不当新证据或用户批准，不借用其他聊天上下文。

`wake` 带 `current_task`；任务切换、规则不确定、错误或冲突用 `autopilot_search_tick`，闲聊免查。工具已知就直调；`functions.exec` 精确匹配工具名并 await，不打印全工具目录或无关 schema。调用示例：

```javascript
const n="search_memory",a={query:"<主题>",scope:"all"};
const t=ALL_TOOLS.filter(t=>t.name===n||t.name.endsWith("__"+n));
if(t.length!==1)text(t.map(t=>t.name));
else{const r=await tools[t[0].name](a);if(r.isError||!r.content?.length)text(r);else for(const b of r.content)text(b.type==="text"?b.text:b);}
```

## 结果与失败

`readback_verified=true` 已核 SQLite 和普通检索，复用完整 `knowledge_changes` 展示实际标题、正文；缺标记、结果缺失或新冲突才补查。说明 `not_written` 原因，单列 `unfinished_work` 真动作；不写不证明完成。工具错误、异常和非 text 结果完整保留，不隐瞒失败或重包装为成功；失败保留来源，不另建库。

清理原文或删除旧记忆须用户明确授权。对原批次 `prepare_session_distill(batch_id=..., cleanup_processed=true)` 预览，核对范围后已有同范围授权就加 `apply_cleanup=true` 执行，不重复询问。保留最终 Note 和可独立接续的必要交接；原项目待办未执行不自动阻止清理。未读、待补判断、证据仍依赖将删材料、活跃／变更来源或回读失败均保留；共享库不得整库删除。保存与物理删除分别报告。
按原批次逐场报告清理结果和保留原因。使用各场的已核对修订、知识与 Note 回读、原生文件或数据库记录范围及执行收据来对账。会话数、文件或记录数、知识条数分别列出。有完整审阅和 Note 的零知识会话可以达到清理条件。

暂停、继续和清理复用返回的 `inspect_arguments/resume_arguments/continue_arguments` 与原 `batch_id`；`pause=true` 不推进，用户明确继续才 `continue_batch=true`。`retry_failures=true` 只重试活动批次可重试失败，来源／revision 错误保持停止；不借重试换源或改写已完成任务。

用户问自动运行时，区分来源捕获、后台完成和实际召回；安装、服务存活或排队不是执行成功。仅用户要求启用自动接入或修复该接入时使用 `get_project_status` 与既有宿主设置，正常检索和人工整理不重复安装。
