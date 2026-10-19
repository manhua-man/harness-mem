---
name: hm
description: Inspect automatic memory and review, correct, or delete stored knowledge.
metadata:
  wireFormatVersion: hm-wire-v3.5
---

# hm

日常记忆由宿主自动记录、后台整理并按任务召回；用户正常聊天，无需逐场要求“记住”。`hm` 用于查看自动记忆和审查、纠正、删除已存内容，不提供手动记住或批量整理入口。首次接入准备自动链路，之后不把内部命令、编号或逐项审批交给用户。

## 调用与读取

已知工具直调；`functions.exec` 全动作按例精确匹配并 await，禁 description/服务前缀泛查、打印全目录/schema。同名先确认 HM；读取换 `search_memory`/参数。

```javascript
const n="search_memory",a={query:"<待查阅或审查的主题>",scope:"all"};
const t=ALL_TOOLS.filter(t=>t.name===n||t.name.endsWith("__"+n));
if(t.length!==1)text(t.map(t=>t.name));
else{const r=await tools[t[0].name](a);if(r.isError||!r.content?.length)text(r);else for(const b of r.content)text(b.type==="text"?b.text:b);}
```

`search_memory(query=<已知标题或主体+缺主题>)` 默认全部含 `global`，任务项目不筛选；仅依用户限 `scope="project"`，误限取消，明确范围不扩大；空查询浏览。回忆当前知识、现状真源、已核更正优先旧原文。同主题合查，复用未变完整源及 `wake/context_injection/statement` 全文，禁换词/入口重查；仅缺答/冲突/源变/截断补读，不限必要检索次数。

完整目标已返回就回答；仅缺答才沿 `continuation.arguments` 原样翻页，标题按返回 `detail="full"` 读，查看全部须读完页。`wake` 带 `current_task`，无任务仅提示可用；切换/规则不确定/错误/冲突用 `autopilot_search_tick`，闲聊免查。

## 审查与更正

先搜索已存内容。纠正时用原样返回的 `target_knowledge=[<旧条目>]` 和当前纠正会话调用 `prepare_session_distill`，完整读取固定来源；已有候选或任务可按其返回合同继续审查。`inspect_sessions` 用于检查自动链路的来源覆盖或失败，不让用户选会话来完成日常记忆。自动处理的完整取舍合同在内部 `hm-distill` 指令中。

宿主身份和执行说明不作用户决定。更正保留说话人、来源时期与适用范围；明确未定/未知/未批准保留为状态，缺用户回应不能推断实际未定或拒绝。`verification_refs` 只用准备值及 `kind,exchange_index,content_sha256,role` 四键，index>=1；用户证据为 `user_statement/user`，助手报告为 `source_report/assistant`，不升为外部事实或用户批准。exchange 禁用 locator，文件证据另取仓库路径。

依 `finalize_contract.instructions/required_fields/allowed_values`，复用当前事实，以 tool/填好 `finalize_contract.args_template` 换上例 n/a 直调，禁查/打印收尾元数据。模板非事实，点/项目/job/引用实填。旧/原始/未就绪缺合同沿原流程，无新门禁。仅缺字段且合同未说明才查该工具真实 schema。

约定/条件保留完整，避免同旧条竞争替换。完整 `semantic_review`：总结具体12–2000字符，矛盾/未完成为字符串数组，后者仅真实动作。`add/confirm/refine/replace` 须 `verified`；`not_applicable` 不可新增/丢弃明确约定。

目标原样取搜索 `title`/完整旧 `statement`/`project_name`，仅有 `module` 才带。确认/替换整旧行数组放各点 `memory_points[i].target_knowledge`，`add` 无目标。运行时派生项目/job/category/source，保留验证/事务/回读；已有 suggest 不重交。无长期价值 `no_write/reject`，不逐句建候选/提升或仅因缺长期证据挂起。

更正完整准备，搜索整旧行作目标；运行时唯一匹配/CAS旧正文，新文 `content`。准备顶层 `target_knowledge` 仅绑现有 owner/source，不代各点目标，收尾顶层禁放。同归属直收尾；跨项目带 `target_knowledge=[<旧条目>]` 重备同一完整源。事实不选 owner；歧义留旧，免用户管项目/批同项重试；删除先搜。明确新措辞优先原样保存，只改指出内容；其余条件/例外/未定、规则/附加条件守原范围，不为润色重写；旧记忆非新说法证据。

## 自动状态与结果

`readback_verified=true` 已核 SQLite/普通检索，复用 `knowledge_changes`；缺标记/结果/新冲突再查。展示实存标题/正文、`not_written` 原因、`unfinished_work` 真动作；不写不证明完成。text/错误/异常/非text原样完整转交，禁省失败/重包装。失败保留来源并修复自动链路，不要求用户改为逐场手动记住，也不另建库。清原文/旧记忆须用户明示。

用户问是否自动运行时，区分来源捕获、后台完成和实际召回，只报告已观察的状态。首次启用或接入故障沿现有 `get_project_status` 与宿主设置处理；文件存在、服务存活或任务排队不算自动记忆成功。正常使用不反复要求安装、开关后台或执行检查清单。
