# Distill 验收测试计划

## 1. 目标

这份文档只定义可执行验收，不重复
[五模块架构合同](memory-adoption.md)或[存储改造计划](roadmap/knowledge-truth-separation.md)。
通过不代表“函数存在”或“job 显示 completed”，而是证明一个会话已经完成接入、提取、逐点验证、归纳吸收，以及干净检索或明确的不写入结果。

`review` 和 `dream` 的治理反馈边界由架构合同定义；本计划只验证它们是否通过重新验证和归纳吸收改变当前知识，而非绕过该边界写入。

成本是横切门禁：记录完整响应、模型调用和端到端耗时，但成本下降不能抵消错误写入。

### 模块合同与验收映射

每个结果必须标记所属模块，不能用一个“蒸馏通过率”掩盖局部退化：

| 模块 | 处理单位 | 必须测量的质量信号 | 本计划的主门槛 |
|---|---|---|---|
| 0. 会话接入与生命周期 | 会话 + 不可变 revision | 漏会话/漏内容/重复、revision 可回查、重试终态、源文件安全、回执绑定 | A5、C、E、F4、F5 |
| 1. 提取 | 一场会话中的所有独立候选点 | 漏晋升点、错误压成一条、候选原子性、来源覆盖；不得提前决定 disposition/title/module | A1–A5、F5、F8 |
| 2. 验证 | 单个候选点 | 来源真实性、内容成立性、逐点独立、后续误判率 | B1–B6、F8、F10 |
| 3. 归纳吸收 | 已验证点与 SQLite 当前知识的对照 | 垃圾写入、过宽/重复/混杂、规范与实现混淆、自然功能模块组织、事务原子性、临时材料清理 | B1–B4、F8–F10 |
| 4. 检索使用 | 任务/查询 + 返回的长期知识 | SQLite authority/派生索引一致性、找回率、精确率、去重、上下文成本、内部信息/旧内容泄漏率 | F11、G |

`ANSWERED` 只证明第 2 模块的证据问题已回答；它不是第 3 模块必须写入长期知识的
通过章。

当前的物理拆分、六会话隔离验收和真实数据迁移授权边界，见
[Knowledge Truth Separation](roadmap/knowledge-truth-separation.md)。F8–F11
继续作为该计划的质量夹具；旧版本号不是“候选与长期知识已物理分离”的完成声明。

`budget_tokens=3000` 只作为 compact 完整响应的软目标。测试不得通过裁剪 JSON、
丢 exchange 或截断原文来满足预算；超出时必须保留完整结果并报告扩张原因。

## 2. 三层测试结构

| 层级 | 何时运行 | 使用真实模型/Hook | 目的 |
|---|---|---:|---|
| L1 确定性回放 | 每次提交 | 否 | 快速保护每个分支和负例 |
| L2 隔离运行时闭环 | PR、发布前 | 默认不使用模型 | 执行真实存储、govern、finalize、Note 和检索链 |
| L3 Desktop 原生验收 | 发布前、Hook 或 provider 改动后 | 是 | 证明原生 Stop Hook 和后台 worker 真正触发 |

L1/L2 使用临时数据目录，不读写用户的真实记忆库。L3 最多使用三个专用测试会话，
不得拿整个历史 backlog 充当测试夹具。真实库中的原文删除策略始终保持关闭。

## 3. 标准夹具

所有回放固定使用下面七个小型 session，避免每次换材料导致质量比较失真。

| 夹具 | 内容 | 预期 |
|---|---|---|
| F1-noise | 问候、临时状态、一次性输出、未完成的 Goal/Read/Write/Acceptance 任务模板 | 无长期候选，有可读 Note；模板字段不得被误写成项目规则 |
| F2-preference | 用户明确要求“降低耗时和 token，但保持提炼效果” | 形成一条 user-statement 偏好 |
| F3-partial | 已验证偏好 + 一个明确未完成事项 + 被替代的旧方案 | 偏好晋升、handoff 落盘、Dream 不运行 |
| F4-revision | 同一 session 先后产生两个 native revision | 两份可读会话总结，latest 指向较新 revision；Note 不作为当前记忆或知识历史 |
| F5-long | 至少 60 个 exchange，价值信号位于开头、中间和结尾 | compact 索引完整，定向 drilldown 命中三处 |
| F6-raw | 包含精确命令、版本、错误文本和跨 chunk 边界 | raw 逐块覆盖且内容 hash 相符 |
| F7-legacy | 只有旧 Observation，没有 native transcript | `legacy_partial`，不能晋升为完整事实 |

每个夹具保存：原生输入、预期 exchange 数、预期信号、允许形成的精确候选、禁止形成的
候选以及预期 Note 摘要。夹具中不放真实用户数据、密钥或绝对路径。

### 质量夹具（F8–F11）

F8–F11 是下一实施列车必须满足的隔离质量夹具。它们不证明候选与长期知识
已经物理分离；当前范围与交付顺序由
[Knowledge Truth Separation](roadmap/knowledge-truth-separation.md)定义：

| 夹具 | 内容 | 预期 |
|---|---|---|
| F8-multi-promotion | 一个会话同时含新事实、应修订事实、已有重复、临时命令和未完成事项 | 各点独立得到 add/refine/confirm/no_write/handoff；会话汇总为 partial |
| F9-request-vs-preference | “这次给我看清单”与“以后默认给完整清单”并存 | 前者 no_write；后者改写成一条完整未来行为规则 |
| F10-assimilation-conflict | 当前 SQLite 知识、近似候选、较窄新结论和相反结论 | confirm 不重复；refine 原子替换；真正冲突不写知识库 |
| F11-clean-retrieval | SQLite 当前知识与 job-scoped evidence/reason 处理记录 | 默认检索只返回标题+正文；真实来源可重新打开；终态 job 临时材料按策略清理 |

禁止写入的一次性请求、会话叙述、标识符、路径、计数和回执必须作为回归样本。
任何未来迁移 cohort 都由实施计划冻结内容哈希；本测试计划不保存会漂移的实时数量或
历史清单状态。

## 4. 路径测试矩阵

### A. 证据读取模式

| ID | 路径 | 输入 | 必须直接证明 | 负例 |
|---|---|---|---|---|
| A1 | semantic compact | F5，软目标 3000 | 完整响应可解析；全部 exchange 有索引；`response_budget.actual_tokens` 与完整序列化结果一致 | 禁止为了 3000 tokens 丢掉尾部 exchange |
| A2 | semantic full | F5，显式 `detail_level=full` | full 比 compact 提供更多语义内容；source revision、覆盖率和判断结果相同 | 未显式请求时不得自动退化成 full |
| A3 | exchange drilldown | F5，指定开头/中间/结尾索引 | 返回所有指定的完整窗口；不改变 job 状态和 checkpoint | 越界索引必须结构化失败，不能返回相邻内容冒充 |
| A4 | query/chunk drilldown | F6，关键词及 chunk index | 精确命令、版本和错误文本可按 hash 对上原文 | 无匹配查询返回空结果，不得编造 proof |
| A5 | raw lossless | F6，`evidence_mode=raw` | 每个 chunk 按序 submit；finalize 前覆盖率为 100%；原文未截断 | 漏一个、乱序或 hash 错误时 finalize 必须失败关闭 |

### B. 治理结果分支

| ID | 分支 | 输入 | 必须直接证明 | 负例 |
|---|---|---|---|---|
| B1 | promote | F2 | 仅形成一条精确偏好；Answer Gate 为 `ANSWERED`；经归纳吸收写入当前知识；正常检索命中 | assistant 自述或未验证 transcript 不得冒充用户偏好 |
| B2 | partial | F3 | 已回答候选独立晋升；handoff 带同一 `distill_job_id` 并可读回；Dream 不运行 | 未绑定 job 的 handoff 不得满足当前 job 的 durable signal gate |
| B3 | zero-candidate | F1 | challenge 完整、结果为 `no_candidate`、Note 有主题和结果、无 pending 垃圾 | 检测到 preference/decision 信号却未逐项解释时 finalize 必须拒绝 |
| B4 | old statement replaced | F3 | 旧方案被替代写入 summary/outcome，不作为当前候选证据冲突；偏好仍晋升 | 当前候选自身证据冲突时必须阻止晋升 |
| B5 | legacy partial | F7 | 结果明确标记 `legacy_partial`，只供诊断，不声称完成 lossless distill | 不得从 Observation 单独生成已确认事实 |
| B6 | policy recheck | 一个旧版错误 `no_candidate` job + F2 信号 | 显式再次处理创建新 job；旧 completion 不变；新 job 可正确晋升 | 已有充分 signal-specific rationale 时不得重复创建 recheck job |

### C. 用户入口和调度

| ID | 入口 | 测试方式 | 必须直接证明 | 负例 |
|---|---|---|---|---|
| C1 | 在 `hm` 中指定单场会话 | F2 | 直接选择最新 eligible job；常见路径为 prepare→finalize；返回可读摘要和 Note | session 属于其他项目时不得越界领取 |
| C2 | 显式批量 | F1、F2、一个故障夹具，调用者指定 `limit=3` | 只处理调用者选定的 3 个；按序；中间失败只 defer 当前 job，后续继续 | 同一 job 不得被重复领取或生成重复候选 |
| C3 | 自动 Desktop Hook | 新建专用 Codex 会话后结束任务 | 原生 Stop receipt、后台 job、provider receipt、finalize、可读 Note 和正常检索对应同一会话 | 只有 queued/completed 字段而没有可读总结/检索结果时不能判通过 |
| C4 | backlog 公平性 | recent 与 oldest eligible 都能继续进入队列 | 按队列顺序处理；不因固定批次或每日额度阻塞 | 被有效 lease 占用的 job 只能 skip，不能错误 defer |

### D. 证据准入

| ID | 证据类型 | 通过条件 | 负例 |
|---|---|---|---|
| D1 | repository | 项目相对路径和当前 SHA-256 可重验 | 文件变化后旧证据变 `STALE`，不得晋升 |
| D2 | user_statement | user role exchange index 和完整窗口 hash 对上明确陈述 | assistant 转述不能算 user statement |
| D3 | transcript | 只能形成 `unverified` 诊断结果 | 不得通过提高 confidence 绕过 Answer Gate |

### E. 恢复、幂等与隔离

| ID | 场景 | 通过条件 |
|---|---|---|
| E1 | finalize 重放 | 返回同一 completion、promotion 和可读 Note，不重复写当前知识 |
| E2 | review lease 竞争 | 只有 owner 能写候选/finalize；过期后可恢复；两个 worker 不产生双写 |
| E3 | provider 失败 | 当前 job 进入 retry/defer；后续 job 不受阻；不生成伪 Note |
| E4 | Note 写入中断 | 临时文件不成为 latest；重试后 latest 指向完整可读的会话总结 |
| E5 | 项目隔离 | 本次显式项目 scope 只处理归属该项目的 session；project A 的 session、候选、handoff 和 SQLite 知识不出现在 project B；不依赖项目白名单 |
| E6 | source retention | 默认 `retained`；临时夹具中显式启用删除才测试 `deleted/partial_failure/unsupported` |

### F. 归纳吸收

| ID | 场景 | 必须直接证明 | 负例 |
|---|---|---|---|
| F-A1 | 单会话多晋升点 | F8 每个点都有独立 verification 和 terminal disposition；提取输出仅含 claim + source locator | 提取不得产生最终 disposition、title 或 module，不得因一个 handoff 阻止其余点 |
| F-A2 | 新增 | 新事实只在 SQLite `knowledge_entries` 写一条原子知识，并有最小真实来源与 verified 日期 | 证据 ANSWERED 但内容 task-local 时不得新增 |
| F-A3 | 修订/替换 | 同一 SQLite 事务删除旧条目并写入新条目；普通搜索只找到新说法 | 不得保留旧知识版本、归档副本、修改记录或撤销链 |
| F-A4 | 确认 | 已有 SQLite 知识条目数和正文均不增加 | 文本略有差异不得自动当新知识，也不得永久保留无价值确认详情 |
| F-A5 | 一次性请求与长期偏好 | F9 分别得到 no_write 与规范化 future behavior | 用户确实说过不能单独证明长期价值 |
| F-A6 | 冲突 | F10 冲突留在 job 生命周期并阻止 SQLite 当前知识变更 | 不得用 provisional 降权掩盖冲突，不得进入 normal retrieval |
| F-A7 | 幂等 | finalize/replay 的 idempotency key、SQLite revision、Note 内容和最终知识一致 | 重放不得重复新增或重复替换 |
| F-A8 | 非法/矛盾候选 | reject 作为独立 job 终态，不写 SQLite knowledge | 不得把 reject 和合法但非长期的 no_write 混为一类 |
| F-A9 | 事务中断恢复 | SQLite commit 前当前知识不变；commit 后通过 idempotency key 完成 receipt/Note/cleanup；数据库 inode 不替换 | 不得出现半条知识、半次替换，或把 derived index 当 authority |
| F-A10 | 自然模块组织 | 模型结合当前项目知识与已验证新知识形成稳定的功能模块/子模块；无硬编码允许列表 | 内部类型、候选阶段、模型随意的过程标签不得成为展示栏目 |

### G. 检索使用

| ID | 场景 | 必须直接证明 | 负例 |
|---|---|---|---|
| G1 | 默认检索投影 | F11 只返回标题和知识正文 | 不得泄漏 session/job/candidate/evidence ID、hash、reason code、内部类型或处理阶段 |
| G2 | 显式来源与真实复核 | 同一知识可按需取得最小来源定位并重新读取真实目录/配置/网页/API 等权威来源 | 旧结果、hash、reason code 或数据库判定不得自证当前仍成立，也不得提供旧知识版本 |
| G3 | 当前版本唯一性 | refine/replace 后 SQLite 当前知识与默认检索只保留 replacement | 旧派生索引残留即失败 |
| G4 | 确认去重 | confirm 证据不增加搜索命中数 | 同义表达不得占据多个 top-k 槽位 |
| G5 | 当前记忆隔离 | 旧兼容行、未完成材料和已删除内容在所有当前记忆入口零命中 | 任何当前记忆入口读取旧行即失败 |
| G6 | 候选源隔离 | 默认 memory search 只从 SQLite 当前知识或同代派生索引取候选；原文走显式 raw/timeline/observation/session-history 路径 | 仅在渲染层隐藏 Observation ID 但仍让 raw 占据 top-k 即失败 |
| G7 | 单一真源与展示 | 删除全部 Markdown export 不改变 wake/search；按需可从同一 SQLite snapshot 确定性重建 Markdown；手改 export 不改变知识 | Markdown 或 derived index 不得反向覆盖 SQLite |
| G8 | 索引内容边界 | FTS/vector 只索引 `module_path + title + statement` | ID、source locator、job/reason/receipt、confidence/tier 不得进入 embedding 或关键词候选 |
| G9 | 稳定 ID 边界 | refine/replace/feedback 可用稳定 ID 指定唯一当前知识 | ID 不得出现在普通结果或 Markdown 默认展示中 |

### H. 受控迁移（需单独授权）

| ID | 场景 | 必须直接证明 | 负例 |
|---|---|---|---|
| H1 | 固定 cohort | preview 绑定精确 ID、payload hash、project、cutoff 和 cohort fingerprint | 不得用当前 provisional 总数替代固定清单 |
| H2 | cohort 漂移 | 任一 payload/generation 变化或实时条目增加时，旧 manifest apply fail closed | 旧 manifest 不得因为实时总数碰巧相同而继续 |
| H3 | 缺失记录 | 当前缺失的 ID 只有在原始清单和来源给出直接处理结果时才算 accounted | “数据库里没有了”不是成功清理证据 |
| H4 | delta cohort | 新增 archive-derived provisional 按项目授权和 provenance 单独冻结/守恒 | 不得顺带修改其他项目全部 provisional |
| H5 | 中断与索引 | 在现有 SQLite inode 内事务更新；commit 后 derived index 可从 SQLite 重建 | 索引成功不能掩盖 SQLite 部分写入，不得替换数据库文件 |
| H6 | 中断后继续 | 在同一 SQLite 数据库上验证中断后可继续，当前知识与检索仍一致 | 不制作会话备份，不把中间文件当作恢复链，也不得覆盖真实库的新内容 |

## 5. 模型样本质量

F1、F2、F3 只判断固定输入是否得到正确、严格可解析的结果。成本和耗时留在
报告里供排查，不参与这个正确性结论；所选宿主 CLI 没有提供 token 用量时记录
`null`，不能填零、估算或声称成本已经验证。

### 每个模型样本必须记录

- prepare 返回的完整序列化响应 tokens，而不只是 evidence 部分；
- provider input/output/total tokens（宿主 CLI 提供时）；否则记录 `null`；
- provider 和端到端 wall time；
- 是否得到预期候选、handoff 与未完成状态。

三个样本必须全部通过质量检查，任何严格 JSON 解析失败、候选错误、证据类型错误
或未完成状态错误都使本项失败。固定样本使用项目选择的宿主 CLI；模型只由该 CLI
的用户配置决定，harness-mem 不提供第二个模型覆盖入口。本验收不维护第二套基线或
历史文件。

## 6. 执行顺序与停止条件

### 每次提交

1. Ruff、Mypy；
2. A/B/D/E 对应的确定性测试；
3. `code/tests/test_public_docs_lifecycle.py` 与 MCP surface contract；
4. 全量 pytest；
5. 运行 `.codex/outcomes.json` 中的隔离 outcome probes。

任何 lossless 覆盖、Answer Gate、job 归属、Note 可读性或项目隔离失败，立即停止，
不得继续跑昂贵的模型测试。

任一隔离六会话运行失败后，必须先冻结该次失败输入与回执，并用一个定向、确定性回归
测试复现根因；该测试和对应最小门禁通过前，不得启动下一轮完整六会话。多个运行时修复
应先在定向门禁中收敛，最后只用一个全新输出目录做从零终验，避免把真实模型运行当作
逐行调试器。

### 发布前

1. L1/L2 全绿；
2. 运行 outcome-verifier；其中后台 Hook 检查先让项目所选 CLI 处理一次 F2，
   通过后才执行一个新的隔离 Hook 全链路；
3. 要求所有 required claim 通过；
4. Doctor 不得出现与本次路径有关的新 HM-* 警告。

对包含 autonomous runtime 的改动，先完成并冻结受 runtime fingerprint 覆盖的源码，
再通过项目选择的宿主 CLI 验证严格 JSON、Hook 不可重入和协议兼容，最后触发
一次真实 Desktop Hook `--wait` 并验证它唤醒的 Dream 终态。endpoint、凭据和模型配置
仍由宿主 CLI 管理。若这些运行时文件之后再变更，
旧 receipt 不再是当前代码的直接证据，必须重新触发；不能只重跑单元测试或 outcome-verifier。

当前实施列车按 [Knowledge Truth Separation](roadmap/knowledge-truth-separation.md)
的 P0–P6 顺序启用相应夹具：P0/P1 对应 `0.9.16`，P2 对应 `0.9.17`，P3
对应 `0.9.18`，P4 对应 `0.9.19`，P5 是 `0.9.20` 的隔离六会话验收，P6 是
`0.9.21` 已完成的一次经授权真实旧记忆收敛。它们是施工包，不是额外产品模块。隔离数据目录中的
cohort/delta 演练和新的真实多晋升点 Desktop 会话都必须证明 Hook → job → 逐点验证
→ 归纳吸收 → Note → 干净检索；“provider 返回合法 JSON”或“job completed”都不是结果证据。

`0.9.20` 已发布 P0–P5：
6 个 `harness-mem` 作业、Note 和 Answer Packet 全部终态持久化，12 条当前知识均从
SQLite 正常回读；处理前冻结的预期晋升点 oracle 绑定六个源文件哈希，并逐场核对提取、
验证、吸收和真值 lineage，真实运行时数据指纹未变化。新鲜 Desktop Hook 已绑定本次
dispatch generation、session、job、Provider 与 Note，完整 outcome contract 为 14/14 passed。
P6 已在一个明确的 `harness-mem` 范围内完成；不得因此自动处理其他项目或未来历史批次。

Codex Stop 后的 rollout 可能与 Hook 短暂并发。Hook 必须按 `trigger_id` 定向同步该
原生会话，并使用有界重试等待文件可见；不得依赖常规增量扫描游标，因为历史 backlog
可能使扫描窗口连续错过刚结束的会话。只有该 trigger 对应的 job、可读 Note 和检索回读
全部可验证，才算 L3 通过。

### 仅在相关代码变化时追加

- 修改 manifest/budget：运行 A1–A5；
- 修改治理/finalize：运行 B1–B6、D1–D3、E1–E2；
- 修改 Hook/provider/Dream：运行 C3–C4、E2–E4、宿主 CLI/Hook 重入/协议隔离夹具，以及真实 Desktop Hook → Dream 终态探针；
- 修改 Note：运行 F4、B2、E1、E4；
- 修改清理策略：只在临时数据目录运行 E6，不在真实用户库试删。

## 7. 最终报告格式

每轮验收只输出一张用户可读卡片，详细 ID 放在检查附件：

```text
Distill acceptance: PASS / PARTIAL / FAIL
Paths: 28/28 passed
Hook → Job → Note → Retrieval: verified
Quality: expected 3/3, false writes 0
Cost: compact 2,840 tokens; provider usage unavailable from this CLI; 12.4s
Regression: tokens -8%, duration -14%
Remaining gaps: none
```

判定规则：

- `PASS`：所有 required 路径都有直接结果证据；
- `PARTIAL`：实现或测试存在，但至少一个用户结果只有支持证据；
- `FAIL`：出现错误晋升、漏读、跨项目污染、双写、Note/receipt 不一致或虚假完成；
- `BLOCKED`：真实 Hook、模型授权或必要宿主不可用，必须明确“未运行”，不能写成通过。

## 8. 首轮建议批次

首轮不碰历史 backlog，按以下四批执行，便于定位故障：

1. 回放批：A1–A5、B1–B6、D1–D3、E1–E6；
2. 隔离闭环批：F1、F2、F3、F4；
3. 成本批：F1、F2、F3 各一次，固定模型与配置；
4. 原生批：一个新 Desktop Hook 会话，再运行完整 outcome-verifier。

四批全部通过后，才恢复历史 backlog。backlog 是生产工作负载，
它可以发现新的真实案例，但不替代上述可重复测试；运行时不再按批次或 UTC 日期限制处理量。

仅在 P5 的六会话隔离验收和用户内容确认通过后，才可追加受控迁移批。它必须先冻结
内容寻址的 cohort 与授权增量，完成隔离回滚演练，再逐条通过正常 search 回读保留或
替换结果；被拒绝、替代或候选记录在默认检索中必须零命中。

需要单独诊断模型对 F1/F2/F3 的处理质量时，可运行：

```bash
python -m harness_mem.qualification.distill_acceptance \
  --project-root . \
  --output .codex/distill-acceptance-report.json \
  --model-samples
```

runner 从版本化 F1–F11 catalog 计算输入指纹，逐项执行 A1–E6 和 F8–F11 的只读
shadow 检查，并把固定模型样本写入
单独的 `distill-acceptance-report-model.json`。模型调用使用项目选择的宿主 CLI，严格
校验返回的 JSON；报告不读取或保存 endpoint、认证 header 或 bearer token。验收应覆盖
不同宿主 CLI 的 JSON 输出差异，而不能把某一个 CLI 的专属字段当作通用合同。
每个固定模型样本只调用一次，不自动重试；任一样本失败或超时后立即停止后续样本，
报告保持失败，不能用其他运行的成功结果补齐。

## 9. 当前验收：任一宿主接入实际跑通即可

2026-10-07 用户明确：Codex 能正常跑即可，任意一个 adapter 接入通过就算通过；
本次不要求两产品对照，也不要求所有宿主逐个通过。通过仍须观察真实 CLI 处理、
当前知识写入、Note 和普通搜索回读，不以 mock 或状态字符串代替实际结果。
2026-10-07 的 Codex 实际隔离运行满足这一标准；当次核对时源码指纹一致，普通 MCP 搜索
仍找回同一标题和正文，Note 的 SHA256 也一致。2026-10-08 的作者引用和结果展示修复
改变了运行时指纹；旧报告只证明当时版本。同日后续模型与 Hook 尝试见下文，最新
进程收尾修复后的完整链路仍未通过。
自然 Desktop Stop、双产品质量对照和重复性能测量保留为独立后续项，不阻塞本次
单接入功能验收；不因此宣称所有宿主兼容、性能改善或已发布。

截至 2026-10-07，Codex 通过了一次脚本触发的隔离 Hook 闭环；详情和本机证据位置见
[roadmap](roadmap.md#status-released-implemented-and-planned-are-different)。这不是自然
Desktop Stop 事件验收，也不是多场语义质量或完整发布门禁。旧版六会话记录仍是历史
证据，不能自动验证当前改动。下表保留各能力的检查合同；超出上述单接入标准的
对照、自然触发和性能项目属于独立后续检查，不表示所有路径已经通过。
本轮可见结果改动后，重新通过了 Codex F2 预检、隔离脚本 Hook、同一任务的 SQLite/Note/
普通搜索回读，以及一次真实 Codex 完成回复（按明确要求保留测试知识的英文原文）。
`manual_session_batch` 探针新增的可见成果、不写入原因和当前知识视图检查均通过，
`clean_retrieval_boundary` 也通过；证据位于 `.tmp/codex-visible-20261007/`。
独立核对发现展示依赖未进入代码指纹后，已补齐六项依赖并测试漂移拒绝；旧报告在
backend/provider 执行前被拒绝，随后重新通过上述模型、Hook 和回复检查。当前文件为
`fingerprint-fixed-hook.json`、`fingerprint-fixed-reply.json` 与
`fingerprint-fixed-outcomes.json`，不沿用该目录中旧指纹报告作为当前证据。
这不代表自然 Stop、全部回复状态、多场真实 Agent 手工整理或两产品实测对照已通过。

| 验收 | 输入与实际操作 | 必须直接观察到的结果 |
|---|---|---|
| 看见成果 | 用户通过 `hm` 请求整理；覆盖新增、替换、不写入、失败和部分完成 | 当前 Agent 的完成回复直接给出实际知识标题与正文、必要分类和普通原因；不需要用户追问“记住了什么”；语言跟随用户 |
| 查看与找回 | 整理后请求查看当前项目知识，再用普通问题找回并纠错 | 可读视图与 SQLite 当前知识一致；替换或删除后旧说法不再返回；原始会话、内部处理材料不混入当前知识 |
| 同源质量对照 | 上游与 harness-mem 读取同一冻结的虚构来源；处理前固定预期独立知识点 | 分别记录漏点、错误写入、重复、过宽内容、任务交接和可读性；保存各自版本、来源哈希与模型配置差异，不用上游示例替代实测 |
| 中断与继续 | 多场隔离来源、重复已完成 revision、来源读取失败、commit 后中断 | 范围与进度稳定；恢复不重复写；失败来源保留且可按现有规则重试；手工路径在后台关闭时可完成 |
| 真实宿主使用 | 新建专用原生会话，观察自然 Stop，随后通过 `hm` 找回和纠错 | 本次触发绑定到终态 job、Note、SQLite 与检索；脚本直接调用 Hook 的结果单独报告 |
| 成本与质量一起验收 | 同一冻结语料、同一配置下比较改动前后多次完整运行 | 提取、验证、吸收质量和恢复边界不退化；完整耗时及实际输入输出呈可重复下降，报告分布和各阶段开销 |

质量对照优先复用 F1–F11 中的短会话、长会话、多点、冲突、旧事实和未完成工作，
只补确有缺口的最小虚构样本。两边产品独有能力与共同操作分开记录；不要求为了
对照而复制上游的 Markdown authority、固定分批或提交行为。用户操作数、Agent 调用数
和重复读取以实际记录为准；不预设“易用性相同”或“提取质量更好”的结论。

工作树已提供离线质量基线 `harness_mem/qualification/fixtures/quality_baseline.json`：
7 份冻结虚构来源、17 个独立判断点，其中 7 项预期当前知识、3 项任务交接、6 项不写入、
1 项冲突。复用 F1/F2/F3/F5，并补充最小重复、失效及冲突样本；来源和完整语料均有
SHA256。可导出语料和**未运行**的结果模板，再对两份独立采集的完整结果评分：

```bash
python -m harness_mem.qualification.quality_baseline --corpus
python -m harness_mem.qualification.quality_baseline --left a.json --right b.json
```

输入必须覆盖完整来源，包含最终全部当前知识和任务交接（也包括处理前已有知识），
并记录产品版本/revision 和配置。逐字匹配仍须真实来源位置；其他措辞要求对**每项**
输出做显式人工语义核对，不能用关键词或自报 point ID 自动判定。人工映射本身的语义
不由评分器证明。评分报告只核对提交结果；不会调用上游、模型或真实库，不证明实际
持久化、恢复、可读性或真实上游对比。后台须关闭，缺失的成本与操作计量保留未知。

实际采集入口为开发脚本 `code/scripts/run_matched_memory_comparison.py`；
`matched_memory_host.py` 仅把原有 MCP / 上游脚本的来源和输出映射到隔离目录。
两边使用同一冻结来源与初始知识，评判答案不得放入执行项目；真实工具事件、
收尾前材料、正式知识和 Note 各自保留。Agent 回复完成或 job/manifest 标记
只能用于检查是否缺少材料，不代替内容质量、检索回读或人工语义核对。
答案没有提供给执行 Agent，不等于终端已被操作系统限制为无法读取答案；
实际访问与可能污染仍需核对。预检同时检查准确的回复标记与原生工具证据，
每次模型调用前检查本机与上游源码、配置与来源指纹，工作流返回后也立即检查。

2026-10-07 首次启动停在 CLI 配置解析：临时 MCP dotted key 加引号导致
`invalid transport`，模型未启动，两边正式整理均未运行。失败证据保留于
`.tmp/quality-compare-20261007/actual-pair-01`。参数修正后只执行了不启动模型或
MCP 服务的配置读取检查；不得把它记为真实预检通过或同源对照完成，也不自动
重试失败的模型检查。采集脚本现在在每次模型调用前先做该静态检查。

用户随后明确要求实际对照，第二次独立运行保留于
`.tmp/quality-compare-20261007/actual-pair-02`。Codex 模型已启动，但只读
`inspect_sessions` 要求确认，而非交互 CLI 的确认策略为 `never`，工具被拒绝。
预检耗时 29.098 秒，CLI 回报 60,085 输入 / 247 输出 tokens；正式整理和上游
模型调用均未开始。进程返回零、模型回合完成不等于原生工具预检通过。
随后仅修正该隔离测试服务的本次调用授权参数，不改变全局配置；这次失败
不能记为两套产品对照通过。失败后停止其余样本、不自动重试的规则保持。

用户明确授权新目录重跑后，`actual-pair-03` 的真实预检通过，全部七场来源可读，
耗时 44.815 秒。正式人工整理运行 246.382 秒，CLI 回报 607,866 输入 tokens
（其中缓存 553,984）和 5,341 输出 tokens；这些不是账单或节省比例。
实际只收尾 F10 与 F9：没有新增或替换知识，仍为预置的三条，任务区留下一个
待验证的审计偏好。F9 的用户陈述引用缺少 `role="user"`，本机验证派生为
`PARTIAL`，没有绕过门槛写入。其余五场未进入完整处理流程，收集器据此停止
上游样本；两套产品尚无可比较的完整结果。重新打开后的普通 MCP 搜索找到原三条，
找不到新的审计偏好，两场的 job 关联 Note 可读且哈希一致，原始来源全部保留。
不能用 CLI 回合完成或两个 `completed` job 宣称整批完成，也没有自动模型重试。
独立只读复核另确认结果表达缺陷：F9 已有待验证交接，finalize 却同时给出
`no_candidate` 与空未完成事项，Note 又声称“已验证”“未完成工作无”。这不是
证据引用被拒绝的原因，但与实际 `PARTIAL/defer` 不一致，需要单独修正。
完整事实与单次计量留在该忽略目录的 `evaluator/attempt-review.md`，不得改写
本次输入或结果来补成通过。

2026-10-08 经用户授权修复上述两处。引用省略作者标记时，从冻结来源核对实际作者，
不是默认当成用户；自动核对目前覆盖支持的 Codex/Cursor 结构化来源，纯文本及其他
宿主保留显式角色的兼容路径，不视为原生作者证明。出现角色分隔符注入时保守拒绝
整份有歧义的来源，不猜测逐点对应。显式角色冲突、来源缺失与摘要不匹配仍不得写入。新增定向隔离
回归覆盖缺省作者的真实写入/重开/普通搜索，以及错误摘要、混合已回答与未完成点、
实际交接事项、Note 字节哈希、幂等回复和批次待办一致性。`deferred`、`conflict` 和
`handoff` 不再显示成 `no_candidate`；校验不足时不能沿用 Agent 自报的“已验证”。
已验证但不新增的点不能显示“已写入”；重新建批不重复报告旧变更，但仍显示选中范围
内的未完成交接事项。
这些测试使用确定性 Agent 决定，不是实际七场模型重跑；改动使此前 Hook 指纹失效，
旧模型与 Hook 成功仅保留为历史证据，不作为新源码的运行证明。

同日经用户授权，在新隔离目录 `.tmp/codex-reverify-20261008/` 用 Codex
重新验证。F2 实际预检只运行一次，返回 `codex provider exceeded 300s`；
中途虽观察到整理输出文件，但进程通信未正常结束，不能认定成功，也不能把报告的
`schema_valid=false` 解读为已经证明 JSON 内容不合法。完整 Hook 与后续手工
模型工作流均未启动，无自动重试。原 `background_memory_hook_flow` 实际结果
断言对该新报告返回 blocked，因预检失败而未执行依赖的 Hook 检查。手工 F8/F9/F10
虚构来源仅完成准备，不是已整理。正式项目仍选 Hermes，真实记忆与旧实验产物未改；
调用结束超时的具体原因尚未证明，新源码完整链路仍未通过。

用户随后授权继续诊断和修复。新隔离目录 `.tmp/codex-pipe-fix-20261008/`
的 F2 实际检查曾在 26.226 秒通过，CLI usage 为 28,562 input + 253 output =
28,815 tokens；后续 Hook 因测试命令项目名与目录解析出的 profile 不一致而失败，
回执 `attempted=0`，不能据此归因到作者引用或模型语义。名称改正后的新运行在 F2
临时目录删除时发生 WinError 32，未生成预检或 Hook 报告；随后停止模型调用，
不把前一次 F2 通过拼接成这次成功。手工三场虚构来源仍仅准备、未真实整理。

最新本地修复将 Codex 输出改为临时文件；只对本次 JSON 调用关闭配置中的 MCP，
不修改宿主设置。Windows CLI 先暂停启动，加入本次调用的进程范围并设置关闭时
终止，再恢复执行，收尾仅终止范围内进程。临时文件分配失败不会创建遗留 lease；
TOML 读取延迟到 Codex 配置检查，安装和锁文件明确声明旧版 Python 的 `tomli`。
39 项定向测试包含真实本地早启动子进程、占用工作目录、执行者异常退出、非零退出、
坏 schema 与超时；另通过 4 项版本检查、scoped Mypy/Ruff、compile 和离线锁文件检查。
没有实际 Python 3.9/3.10 完整运行证明，也未证明最初占用句柄的进程具体是谁。
此次修复再次改变运行时指纹，最新代码未重新调用模型或完整 Hook；现有 Hook 合同
仅检查当前报告是否存在及匹配，结果为 blocked，不是重新执行链路。详细负面记录在
该忽略目录的 `attempt-review.md` 与 `current-contract-report.json`；未运行宽门禁或发布。

2026-10-09 的修复使用普通搜索中的旧标题、正文和可选分类选择修改目标，
不要求用户提供编号。定向回归验证：精确替换与独立新增同时保存；目标缺失、
歧义、变化或属于别的项目时旧内容不变，独立有效新增仍保存，未保存点和来源保留；
重开数据库和再次收尾不重复写入；尚未收尾会话的已存交接事项出现在批次待办。

新隔离证据在 `.tmp/codex-simple-memory-fix-20261009/`：当前代码的 F2 预检、
完整 Codex Hook、SQLite/Note/普通搜索回读及三种重入拦截通过，配置与代码哈希
在运行期间一致。现有 Hook 断言读取本次报告通过；三项隔离运行结果检查另行通过。
随后三场 F8/F9/F10 实际人工整理预检通过，但正式模型回合两次无法启动终端，
报 `helper_unknown_error: setup refresh had errors`，未能读取必需说明。
该隔离 MCP adapter 不提供 `resources/list`，因此没有从它读回说明的替代路径。
没有创建蒸馏 job、Note、交接或新知识，旧三条及来源全部不变。
模型回合正常退出不能代替整理完成，结果为 partial；停止后续模型样本且无重试。
这不改变正式项目的 Hermes 设置或真实记忆，也不证明所有宿主、自然 Stop 或发布。
最终快速测试 lane 为 1413 通过、1 跳过、4 发布门禁未选择；Ruff、全部运行代码
Mypy 和 compileall 通过。这些开发检查不替代仍未执行成功的三场模型手工整理。
独立只读复核确认库与 Note 证据，并指出该手工预检未检查必需说明文件能否读取；
实际失败回复仍展示内部参数及步骤名称。因此普通话失败回复的实际模型验收也未通过，
不能用修改后的说明文字或测试通过掩盖该结果。

后续修复让预检实际核对成功终端读取的完整说明（含 canonical `hm.md`、skill、
引用文件和初始知识），并将当前 MCP 盘点事件与当前项目绑定；不能沿用旧日志或
正常退出码作为通过证据。新的隔离 CLI 预检仅一次终端启动失败就停止，没有重试，
实际回复使用普通话且明确没有改动记忆。Windows sandbox 日志证明读取权限设置
被正在使用的 `node_repl.exe` 阻塞（错误 32）；没有终止宿主进程、修改全局配置
或关闭安全限制。该次失败样本位于 `.tmp/manual-entry-fix-20261009/`，后续改码后
属于历史指纹，不证明当前 CLI 恢复或 Hook 通过。

当前 Agent 模拟手工处理又发现并修复两处实际问题：非法 `semantic_review` 必须在
候选结算及知识写入前拒绝；Codex 新接入的允许对话保存与该不可变版本绑定的真实
用户内容摘要，逐点核验不再因原始宿主日志未落盘而误报作者无法核实。摘要需与完整
有序用户内容及 rendering digest 一致，伪造 User 边界仍拒绝，private 内容不落盘；
旧来源不自动改写。接入与 snapshot 三个 owner 加入指纹及漂移回归。

独立复核又发现外层/内层作者冲突可被摘要路径接受，以及 Note 把确认算作新写入。
现已在解析转换前排除冲突或不合法作者；写入列表仅含新增、补充、替换，不含确认。
真实 adapter 负面回归和仅确认/确认加新增的 finalize/Note 回归通过；旧运行保留为
历史缺陷证据，未直接改写其数据或套用新代码判定。

最终新隔离目录 `.tmp/manual-verified-20261009/` 使用当前指纹，由主 Agent 完整阅读
F8/F9/F10 虚构原文并提出决定，通过既有产品 MCP 的 stdio transport 实际提交。
后台关闭；新增 2、替换 1、确认 1（无重复），一时请求和不成立猜测不写，原始来源
全部保留。普通搜索由初始 3 条变为当前 5 条，旧 sync 说法消失；批次返回两个实际
未完成主题（猜测验证、上线前合同检查），未把它们当成长期知识。这里只证明当前
Agent 的隔离手动模拟，不称独立 CLI 或自然宿主触发通过。
当前 301 项定向测试、4 项版本检查、Mypy 230 文件、Ruff、compile 与 descriptor
核对通过；另行执行的 manual_session_batch、partial_distill_handoff、
clean_retrieval_boundary 三项结果合同通过。快速宽 lane 曾误启动，在缺少新完整 Hook
前置证据时主动停止，没有最终通过结论；不沿用旧 1413 通过数或旧 Hook 作为当前验收。
真实记忆、正式 Hermes 设置与全局安装未修改。CLI 环境恢复及新完整 Hook 仍待验证。

本轮后续修复（2026-10-09）：人工任务保存 `manual_only`，后台排队、指定任务、
prepare、review claim 与后台 lease 调和不接手；尚未绑定的固定来源及 stopped 批次
也不会交给后台，人工入口不能抢占活跃后台 lease。归档 current 范围按保存的绝对
项目 root 重新计算终态与生命周期，排除其他项目、同名异 root 和不明归属；已删除的
已验证来源仍归属原项目，全局排除与不明来源只作为 inventory 诊断。
最新 274 项定向测试和四项隔离结果合同通过，Mypy 230 文件、定向 Ruff、compile
及 descriptor 核对通过。manual 结果探针实际开启后台并指定每个人工 job，provider
调用即失败，实际验证无调用、job/当前知识/原文不变。证据在
`.tmp/manual-background-fix-20261009/`。一次零模型调用的 CLI sandbox 检查仍因
正在使用的 `node_repl.exe` ACL 更新错误 32 失败；未重试模型或执行完整 Hook，
未关闭安全限制或终止宿主。真实记忆、正式 Hermes 配置和全局安装未改。
这些隔离证据不表示独立 CLI、模型语义质量或发布门禁通过；旧 Hook 仍是历史指纹。

独立复核补齐的最终边界：批次冻结与跨连接 claim 使用同一 SQLite 写锁；底层分块
及 review claim 均拒绝未绑定的冻结来源。已有活跃后台任务则不创建 manifest。
归档 completed 重放先验证当前知识、完整来源及 receipt，再调用既有清理 owner；
人工保留来源不删，验证失败不计成功。原文重新出现时重新核对当前字节，不接受旧
删除 receipt；异常收尾用冻结 revision，Note 保留清理前身份。revision 变化只计
一个当前来源状态。最终 18 文件合并回归 415 passed，四项隔离结果检查重跑通过，
Mypy、Ruff、compile 与 diff 检查通过。结果在
`.tmp/manual-background-fix-20261009/outcomes-final.json`，当前指纹为
`sha256:6940734ce7c44fe2d9bb2a81bda78d04064137e5ffa239f32523ff6427f56302`。
未重跑模型或完整 Hook；沙箱错误仍未解除，不能说已经具备发布条件。

操作员重启后授权继续：`.tmp/codex-restarted-20261009/sandbox-probe.json` 保存了
一次新零模型启动检查，仍失败。当前日志再次报 `node_repl.exe` ACL 更新错误 32，
只读进程检查发现当前桌面宿主的 Codex 子进程已重新启动多个同路径工具进程。
指纹未变；没有启动模型或完整 Hook，没有结束共享工具、关闭安全限制或改全局设置。
重启本身未解除占用，需先安全处理宿主运行时占用，不能继续盲目重试模型。

2026-10-11 的宿主共存修复已通过零模型实际检查：保持 Codex CLI `0.162.1` 与原
runner，只替换为官方 `0.163.0-alpha.5-win32-x64` 的有效 OpenAI 签名 setup helper，
保留签名原件，不使用无签名编译产物。旧 helper 在相同桌面共存条件下仍失败，
随后两次普通安装入口均完整读取说明、允许项目内写入、拒绝项目外写入；外部文件
在沙箱外可写，沙箱内明确返回 `UnauthorizedAccessException` / `0x80070005`。
实际 helper 路径/hash、同 PID 同创建时间的桌面/Node/Swift、配置及代码指纹均已核对。
证据在本机忽略目录 `.tmp/desktop-runtime-fix-20261011/`；本轮不结束工具或重启，
不降低沙箱权限、不调用模型、不处理真实记忆。此结果只解除当前本机的沙箱占用
阻塞，不代替新的 F2 模型预检、完整 Hook、长期运行或发布门禁。该本机辅助程序
替换不是完整官方版本升级，Codex 重装可能覆盖它。

同日随后执行一次新 Codex F2 预检并通过，才启动一次完整隔离 Hook：预检
27.563 秒（28,791 input + 255 output = 29,046 tokens）；Hook 70.61 秒，三个语义
阶段合计 86,013 input + 631 output = 86,644 tokens。当前 `6940734...` 下保存并
普通搜索回读 1 条虚构项目知识；两份 Note 与 receipt 哈希一致，三种重入实际
阻断，下游新 job 为 0。收据在本机忽略目录 `.tmp/codex-core-chain-20261011/`。
独立只读核对发现原搜索响应未保留，随后只补一次同数据目录普通 MCP 搜索，
保存 `search.responses.jsonl` 并比对 SQLite 标题/正文；没有重跑模型或 Hook。
初始额外字节守护因真实 transcript ledger 同期变化而失败，`execution.json`
及 `contract-hook.json` 的失败/blocked 记录保留，不改判。同窗真实桌面已有任务
在 15:00:35 UTC 更新；这支持并发宿主活动解释，不能精确归因所有账本字节差异。
真实当前知识库前后/补核哈希相同且无待处理 WAL/journal，合成来源、任务和两种
Note 不在真实目录；正式 Hermes 设置未改。未放宽原 `background_memory_hook_flow`
expect 断言的 `contract-core-hook.json` 通过，额外保留全账本静止检查失败警告。
通过范围是本次要求的 Codex 核心记忆链路，不是账本冻结、自然 Stop、全部宿主、
语义质量或发布；计量只代表此一次样本，不是费用、平均性能或节省声明。

开销基线必须分开记录预检与工作负载，列出 CLI 启动、完整输入/输出、各语义阶段、
验证与收尾、搜索回读、重试以及工具调用。2026-10-07 首次历史定位样本 Hook 为 76.62 秒，
三个语义阶段合计 CLI usage 为 104,549 input + 752 output = 105,301 tokens；
F2 预检另为 24.158 秒。它们只用于定位问题，不是平均值、费用或节省比例。
缓存 token 和账单缺失时明确不可用；不能用 harness-mem 提示文本大小代替实际 CLI
完整输入，也不能靠截断原文、隐藏失败或跳过逐点判断来制造下降。

所有新模型检查仍遵守单个最小预检→完整 Hook→较宽门禁的顺序；失败或超时按现有
停止规则处理。改动运行代码或相关配置后重新验证，不沿用此次 Codex 的通过状态。
发布前须重新运行当前 required outcome 集合和相关仓库门禁，不把读取旧成功报告
当作新版本的运行验收；真实历史处理与删除仍需各自明确授权。
