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
| 1. 提取 | 一场会话的 0～12 个独立候选点 | 漏晋升点、错误压成一条、候选原子性、来源覆盖；不得提前决定 disposition/title/module | A1–A5、F5、F8 |
| 2. 验证 | 单个候选点 | 来源真实性、内容成立性、逐点独立、后续误判率 | B1–B6、F8、F10 |
| 3. 归纳吸收 | 已验证点与 SQLite 当前知识的对照 | 垃圾写入、过宽/重复/混杂、规范与实现混淆、自然功能模块组织、事务原子性、临时材料清理 | B1–B4、F8–F10 |
| 4. 检索使用 | 任务/查询 + 返回的长期知识 | SQLite authority/派生索引一致性、找回率、精确率、去重、上下文成本、审计/历史泄漏率 | F11、G |

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
| F1-noise | 问候、临时状态、一次性输出 | 无长期候选，有可读 Note |
| F2-preference | 用户明确要求“降低耗时和 token，但保持提炼效果” | 形成一条 user-statement 偏好 |
| F3-partial | 已验证偏好 + 一个明确未完成事项 + 被替代的旧方案 | 偏好晋升、handoff 落盘、Dream 不运行 |
| F4-revision | 同一 session 先后产生两个 native revision | 两份不可变 Note，latest 指向较新 revision |
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
| A3 | exchange drilldown | F5，指定开头/中间/结尾索引 | 返回对应完整窗口，最多 8 个；不改变 job 状态和 checkpoint | 越界索引必须结构化失败，不能返回相邻内容冒充 |
| A4 | query/chunk drilldown | F6，关键词及 chunk index | 精确命令、版本和错误文本可按 hash 对上原文 | 无匹配查询返回空结果，不得编造 proof |
| A5 | raw lossless | F6，`evidence_mode=raw` | 每个 chunk 按序 submit；finalize 前覆盖率为 100%；原文未截断 | 漏一个、乱序或 hash 错误时 finalize 必须失败关闭 |

### B. 治理结果分支

| ID | 分支 | 输入 | 必须直接证明 | 负例 |
|---|---|---|---|---|
| B1 | promote | F2 | 仅形成一条精确偏好；Answer Gate 为 `ANSWERED`；状态为 `auto_confirmed`；正常检索命中 | assistant 自述或未验证 transcript 不得冒充用户偏好 |
| B2 | partial | F3 | 已回答候选独立晋升；handoff 带同一 `distill_job_id` 并可读回；Dream 不运行 | 未绑定 job 的 handoff 不得满足当前 job 的 durable signal gate |
| B3 | zero-candidate | F1 | challenge 完整、结果为 `no_candidate`、Note 有主题和结果、无 pending 垃圾 | 检测到 preference/decision 信号却未逐项解释时 finalize 必须拒绝 |
| B4 | historical supersede | F3 | 旧方案被替代写入 summary/outcome，不作为当前候选证据冲突；偏好仍晋升 | 当前候选自身证据冲突时必须阻止晋升 |
| B5 | legacy partial | F7 | 结果明确标记 `legacy_partial`，只可审计，不声称完成 lossless distill | 不得从 Observation 单独生成已确认事实 |
| B6 | policy recheck | 一个旧版错误 `no_candidate` job + F2 信号 | 显式再次处理创建新 job；旧 completion 不变；新 job 可正确晋升 | 已有充分 signal-specific rationale 时不得重复创建 recheck job |

### C. 用户入口和调度

| ID | 入口 | 测试方式 | 必须直接证明 | 负例 |
|---|---|---|---|---|
| C1 | 指定单 session | `hm-distill <session-id>`，F2 | 直接选择最新 eligible job；常见路径为 prepare→finalize；返回可读摘要和 Note | session 属于其他项目时不得越界领取 |
| C2 | 显式批量 | F1、F2、一个故障夹具，limit=3 | 最多处理 3 个；按序；中间失败只 defer 当前 job，后续继续 | 同一 job 不得被重复领取或生成重复候选 |
| C3 | 自动 Desktop Hook | 新建专用 Codex 会话后结束任务 | 原生 Stop receipt、后台 job、provider receipt、finalize、Note hash 和正常检索形成同一条可追溯链 | 只有 queued/completed 字段而没有 Note/检索证据时不能判通过 |
| C4 | backlog 公平性 | 3 个 recent + 1 个 oldest eligible | recent/oldest 按 3:1 补位；单轮硬上限 3；daily budget 生效 | 被有效 lease 占用的 job 只能 skip，不能错误 defer |

### D. 证据准入

| ID | 证据类型 | 通过条件 | 负例 |
|---|---|---|---|
| D1 | repository | 项目相对路径和当前 SHA-256 可重验 | 文件变化后旧证据变 `STALE`，不得晋升 |
| D2 | user_statement | user role exchange index 和完整窗口 hash 对上明确陈述 | assistant 转述不能算 user statement |
| D3 | transcript | 只能形成 `unverified` 审计结果 | 不得通过提高 confidence 绕过 Answer Gate |

### E. 恢复、幂等与隔离

| ID | 场景 | 通过条件 |
|---|---|---|
| E1 | finalize 重放 | 返回同一 completion、promotion 和不可变 Note hash，不重复写 truth |
| E2 | review lease 竞争 | 只有 owner 能写候选/finalize；过期后可恢复；两个 worker 不产生双写 |
| E3 | provider 失败 | 当前 job 进入 retry/defer；后续 job 不受阻；不生成伪 Note |
| E4 | Note 写入中断 | 临时文件不成为 latest；重试后 immutable/latest hash 正确 |
| E5 | 项目隔离 | 本次显式项目 scope 只处理归属该项目的 session；project A 的 session、候选、handoff 和 SQLite 知识不出现在 project B；不依赖项目白名单 |
| E6 | source retention | 默认 `retained`；临时夹具中显式启用删除才测试 `deleted/partial_failure/unsupported` |

### F. 归纳吸收

| ID | 场景 | 必须直接证明 | 负例 |
|---|---|---|---|
| F-A1 | 单会话多晋升点 | F8 每个点都有独立 verification 和 terminal disposition；提取输出仅含 claim + source locator | 提取不得产生最终 disposition、title 或 module，不得因一个 handoff 阻止其余点 |
| F-A2 | 新增 | 新事实只在 SQLite `knowledge_entries` 写一条原子知识，并有最小真实来源与 verified 日期 | 证据 ANSWERED 但内容 task-local 时不得新增 |
| F-A3 | 修订/替换 | 同一 SQLite 事务替换当前条目并保留支持期内 undo 所需的最小前一版本 | 不得保留两个互相重叠的当前知识或把永久 decision ledger 当作知识历史 |
| F-A4 | 确认 | 已有 SQLite 知识条目数和正文均不增加 | 文本略有差异不得自动当新知识，也不得永久保留无价值确认详情 |
| F-A5 | 一次性请求与长期偏好 | F9 分别得到 no_write 与规范化 future behavior | 用户确实说过不能单独证明长期价值 |
| F-A6 | 冲突 | F10 冲突留在 job 生命周期并阻止 SQLite mutation | 不得用 provisional 降权掩盖冲突，不得进入 normal retrieval |
| F-A7 | 幂等 | finalize/replay 的 idempotency key、SQLite revision、Note hash 和最终知识一致 | 重放不得重复新增或重复 supersede |
| F-A8 | 非法/矛盾候选 | reject 作为独立 job 终态，不写 SQLite knowledge | 不得把 reject 和合法但非长期的 no_write 混为一类 |
| F-A9 | 事务中断恢复 | SQLite commit 前当前知识不变；commit 后通过 idempotency key 完成 receipt/Note/cleanup；数据库 inode 不替换 | 不得出现半条知识、半次 supersede，或把 derived index 当 authority |
| F-A10 | 自然模块组织 | 模型结合当前项目知识与已验证新知识形成稳定的功能模块/子模块；无硬编码允许列表 | 内部类型、候选阶段、模型随意的过程标签不得成为展示栏目 |

### G. 检索使用

| ID | 场景 | 必须直接证明 | 负例 |
|---|---|---|---|
| G1 | 默认检索投影 | F11 只返回标题和知识正文 | 不得泄漏 session/job/candidate/evidence ID、hash、reason code、内部类型或处理阶段 |
| G2 | 显式来源与真实复核 | 同一知识可按需取得最小来源定位并重新读取真实目录/配置/网页/API 等权威来源；支持期内可取得 undo 所需前一版本 | 旧 outcome、hash、reason code 或数据库 verdict 不得自证当前仍成立 |
| G3 | 当前版本唯一性 | refine/supersede 后 SQLite 当前知识与默认检索只保留 replacement | 旧派生索引残留即失败 |
| G4 | 确认去重 | confirm 证据不增加搜索命中数 | 同义表达不得占据多个 top-k 槽位 |
| G5 | 状态过滤 | deferred/rejected/provisional/superseded 默认零命中 | 只有降权而仍在默认结果中即失败 |
| G6 | 候选源隔离 | 默认 memory search 只从 SQLite 当前知识或同代派生索引取候选；原文走显式 raw/timeline/observation/session-history 路径 | 仅在渲染层隐藏 Observation ID 但仍让 raw 占据 top-k 即失败 |
| G7 | 单一真源与展示 | 删除全部 Markdown export 不改变 wake/search；按需可从同一 SQLite snapshot 确定性重建 Markdown；手改 export 不改变知识 | Markdown 或 derived index 不得反向覆盖 SQLite |
| G8 | 索引内容边界 | FTS/vector 只索引 `module_path + title + statement` | ID、source locator、job/reason/receipt、confidence/tier 不得进入 embedding 或关键词候选 |
| G9 | 稳定 ID 边界 | refine/supersede/feedback 可用稳定 ID 指定唯一当前知识 | ID 不得出现在普通结果或 Markdown 默认展示中 |

### H. 受控迁移（需单独授权）

| ID | 场景 | 必须直接证明 | 负例 |
|---|---|---|---|
| H1 | 固定 cohort | preview 绑定精确 ID、payload hash、project、cutoff 和 cohort fingerprint | 不得用当前 provisional 总数替代固定清单 |
| H2 | cohort 漂移 | 任一 payload/generation 变化或实时条目增加时，旧 manifest apply fail closed | 旧 manifest 不得因为实时总数碰巧相同而继续 |
| H3 | 缺失记录 | 当前缺失的 2 个 ID 只有在 event/lineage 给出直接终态证据时才算 accounted | “数据库里没有了”不是成功清理证据 |
| H4 | delta cohort | 新增 archive-derived provisional 按项目授权和 provenance 单独冻结/守恒 | 不得顺带修改其他项目全部 provisional |
| H5 | 中断与索引 | 在现有 SQLite inode 内事务更新；commit 后 derived index 可从 SQLite 重建 | 索引成功不能掩盖 SQLite 部分写入，不得替换数据库文件 |
| H6 | rollback | 仅在无后续 revision 时从受控前一版本恢复，恢复后 SQLite/index/search generation 一致 | 不得覆盖迁移后新增 truth |

## 5. 性能与质量基线

正确性是硬门禁，成本是回归门禁，二者不能互相替代。

### 每个模型样本必须记录

- prepare 返回的完整序列化响应 tokens，而不只是 evidence 部分；
- provider input/output/total tokens；
- prepare、provider、finalize 和端到端 wall time；
- drilldown 次数与扩张原因；
- 是否得到预期候选、handoff、Note 和检索命中。

### 首版门限

以 F1、F2、F3 各运行一次作为固定小样本：

| 指标 | 门限 |
|---|---|
| compact 完整响应 | 默认软目标 3000；超出允许，但必须 `complete=true` 并给 expansion reason |
| provider total tokens | 单样本警戒线 15,000；超过不掩盖正确结果，但阻止发布直至解释 |
| provider duration | 单样本警戒线 40 秒 |
| 端到端 duration | 单样本警戒线 60 秒 |
| 相对回归 | 在同一夹具、模型和配置下，tokens 或耗时较最近绿色基线增加超过 20% 则告警 |
| 质量 | 预期晋升点召回 100%，禁止长期写入 0，逐点 disposition 100%，Note/SQLite/派生索引/检索闭环 100%，终态临时材料清理 100% |

样本少时只报告单次值，不伪装成 P95。累计至少 20 个同配置样本后再报告 P50/P95。
模型、配置或 manifest schema 改变时建立新基线，不把不同条件的数据混算。
自动蒸馏默认使用独立的低推理结构化模型 `gpt-5.6-luna`，不继承交互式编码
Agent 的模型；可通过 `HARNESS_MEM_DISTILL_MODEL` 或 runner 的 `--model` 显式覆盖。
provider 请求门限与 40 秒单样本警戒线保持一致。
最近一次无告警结果单独保存为绿色基线；带成本告警的运行不得覆盖基线，也不得把
总验收状态写成 PASS。
Token 相对回归按单次 usage 判定；耗时的 40/60 秒绝对门限按单次判定。相对耗时
回归需至少 3 个同 fixture/model/manifest 样本，使用最近 3 次中位数与绿色基线比较，
避免把服务端单次抖动误报为产品回归。历史只保存 usage、耗时和输入指纹。

## 6. 执行顺序与停止条件

### 每次提交

1. Ruff、Mypy；
2. A/B/D/E 对应的确定性测试；
3. `code/tests/test_public_docs_lifecycle.py` 与 MCP surface contract；
4. 全量 pytest；
5. 运行 `.codex/outcomes.json` 中的隔离 outcome probes。

任何 lossless 覆盖、Answer Gate、job 归属、Note hash 或项目隔离失败，立即停止，
不得继续跑昂贵的模型测试。

任一隔离六会话运行失败后，必须先冻结该次失败输入与回执，并用一个定向、确定性回归
测试复现根因；该测试和对应最小门禁通过前，不得启动下一轮完整六会话。多个运行时修复
应先在定向门禁中收敛，最后只用一个全新输出目录做从零终验，避免把真实模型运行当作
逐行调试器。

### 发布前

1. L1/L2 全绿；
2. 用 F1/F2/F3 跑一次固定模型样本，保存 tokens、耗时和质量结果；
3. 执行一个新的真实 Desktop Hook 会话；
4. 运行 outcome-verifier，要求所有 required claim 通过；
5. Doctor 不得出现与本次路径有关的新 HM-* 警告。

对包含 autonomous runtime 的改动，顺序必须是：先完成并冻结所有受 runtime
fingerprint 覆盖的源码改动，再触发一次真实 Desktop Hook `--wait`，最后运行
outcome-verifier。若 Hook 完成后又修改了这些运行时文件，旧 receipt 即不再是
当前代码的直接证据，必须重新触发 Hook；不能只重跑单元测试或 outcome-verifier。

当前实施列车按 [Knowledge Truth Separation](roadmap/knowledge-truth-separation.md)
的 P0–P6 顺序启用相应夹具：P0/P1 对应 `0.9.16`，P2 对应 `0.9.17`，P3
对应 `0.9.18`，P4 对应 `0.9.19`，P5 是 `0.9.20` 的隔离六会话验收，P6 才是
`0.9.21` 的经授权真实旧记忆收敛。它们是施工包，不是额外产品模块。隔离数据目录中的
cohort/delta 演练和新的真实多晋升点 Desktop 会话都必须证明 Hook → job → 逐点验证
→ 归纳吸收 → Note → 干净检索；“provider 返回合法 JSON”或“job completed”都不是结果证据。

`0.9.20` 已发布 P0–P5：
6 个 `harness-mem` 作业、Note 和 Answer Packet 全部终态持久化，12 条当前知识均从
SQLite 正常回读；处理前冻结的预期晋升点 oracle 绑定六个源文件哈希，并逐场核对提取、
验证、吸收和真值 lineage，真实运行时数据指纹未变化。新鲜 Desktop Hook 已绑定本次
dispatch generation、session、job、Provider 与 Note，完整 outcome contract 为 14/14 passed。
P6 未获授权，不得因为 P0–P5 通过而自动执行。

Codex Stop 后的 rollout 可能与 Hook 短暂并发。Hook 必须按 `trigger_id` 定向同步该
原生会话，并使用有界重试等待文件可见；不得依赖常规增量扫描游标，因为历史 backlog
可能使扫描窗口连续错过刚结束的会话。只有该 trigger 对应的 job、Note/hash 和检索回读
全部可验证，才算 L3 通过。

### 仅在相关代码变化时追加

- 修改 manifest/budget：运行 A1–A5；
- 修改治理/finalize：运行 B1–B6、D1–D3、E1–E2；
- 修改 Hook/provider/worker：运行 C3–C4、E2–E4 和真实 Desktop Hook；
- 修改 Note：运行 F4、B2、E1、E4；
- 修改清理策略：只在临时数据目录运行 E6，不在真实用户库试删。

## 7. 最终报告格式

每轮验收只输出一张用户可读卡片，详细 ID 放在审计附件：

```text
Distill acceptance: PASS / PARTIAL / FAIL
Paths: 28/28 passed
Hook → Job → Note → Retrieval: verified
Quality: expected 3/3, false writes 0
Cost: compact 2,840 tokens; provider 6,120 tokens; 12.4s
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

四批全部通过后，才恢复历史 backlog 的每批三个会话处理。backlog 是生产工作负载，
它可以发现新的真实案例，但不替代上述可重复测试。

仅在 P5 的六会话隔离验收和用户内容确认通过后，才可追加受控迁移批。它必须先冻结
内容寻址的 cohort 与授权增量，完成隔离回滚演练，再逐条通过正常 search 回读保留或
替换结果；被拒绝、替代或候选记录在默认检索中必须零命中。

统一 runner：

```bash
python -m harness_mem.qualification.distill_acceptance \
  --project-root . \
  --output .codex/distill-acceptance-report.json \
  --model-samples
```

runner 从版本化 F1–F11 catalog 计算输入指纹，逐项执行 A1–E6 和 F8–F11 的只读
shadow 检查，并把固定模型样本写入
单独的 `distill-acceptance-report-model.json`。模型调用使用 `tools=[]`、`store=false`
和严格 schema；报告不保存 endpoint、认证 header 或 bearer token。
