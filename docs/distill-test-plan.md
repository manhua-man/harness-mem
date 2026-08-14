# Distill 验收测试计划

## 1. 目标

这份计划验证的不是“代码里存在某个处理函数”，而是用户交给 harness-mem
一个会话后，系统确实完成了以下闭环：

```text
0. 会话接入与生命周期（授权、revision、job、receipt）
        → 1. 提取多个晋升点 → 2. 逐点验证
        → 3. 归纳吸收（新增/修订/确认/替换/不写/交接）
        → finalize + Session Note → 4. 干净检索或明确的无写入结果
```

测试必须同时回答四个产品问题，并单独记录成本：

1. 接入终态对了吗：宿主会话、项目授权、revision、job、Hook/provider receipt 和源文件生命周期是否可追溯；
2. 读全了吗：原始 revision、chunk 顺序、hash 和 exchange 索引是否完整；
3. 逐点验证对了吗：一个会话中的每个晋升点是否拥有独立证据和状态；
4. 归纳吸收对了吗：应保留的事实完成新增/修订/确认/替换，临时内容没有进入长期记忆；
5. 检索使用对了吗：只返回当前规范正文，Note、审计、ID 和历史内容没有混入默认结果；

成本作为横切门禁：记录 Agent 实际收到的完整响应 tokens、模型 tokens 和端到端耗时，
但成本下降不能抵消错误写入。

`review` 和 `dream` 是归纳吸收与检索使用之间的治理反馈环，不是线性第 5 阶段。

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

### 0.9.13-0.9.15 质量夹具

0.9.13 已把 F8-F11 的只读影子检查加入 F1-F7 和 24 条已发布路径之上，
合计 28 条。0.9.14 已在独立持久化探针中验证多点归纳吸收；F8-F11 仍保留为
不改变生产数据的质量基线。0.9.15 已验证默认 search/wake 隔离原始 Observation，
只有显式 deep recall 才返回原文；用户可见的干净投影字段和历史 cohort 迁移仍未开始。
完整范围见[四阶段记忆质量计划](roadmap/0.9.13-four-stage-memory-quality.md)：

| 夹具 | 内容 | 预期 |
|---|---|---|
| F8-multi-promotion | 一个会话同时含新事实、应修订事实、已有重复、临时命令和未完成事项 | 各点独立得到 add/refine/confirm/no_write/handoff；会话汇总为 partial |
| F9-request-vs-preference | “这次给我看清单”与“以后默认给完整清单”并存 | 前者 no_write；后者改写成一条完整未来行为规则 |
| F10-assimilation-conflict | 当前真相、近似候选、较窄新结论和相反结论 | confirm 不重复；refine 原子替换；真正冲突不写 truth |
| F11-clean-retrieval | 规范正文附带完整 job/evidence/hash/reason 审计记录 | 默认检索只返回 title+statement；显式审计可回查全部来源 |

122 条审计清单中的代表性垃圾记录作为禁止输出回归样本；完整迁移使用清单中的
122 个固定 ID，而不是假设实时查询仍返回 122 条。2026-08-15 只读预检只找到其中
120 条（97 provisional rule candidate + 23 auto-confirmed memory），另有 2 条缺失，
必须通过 lifecycle/lineage 证据解释或阻止完成。迁移期间新增条目形成独立 delta cohort。

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
| E5 | 项目隔离 | project A 的 session、候选和 handoff 不出现在 project B |
| E6 | source retention | 默认 `retained`；临时夹具中显式启用删除才测试 `deleted/partial_failure/unsupported` |

### F. 归纳吸收（0.9.14 已实现）

| ID | 场景 | 必须直接证明 | 负例 |
|---|---|---|---|
| F-A1 | 单会话多晋升点 | F8 每个点都有独立 verification 和 terminal disposition | 不得只保留一条会话总括，或因一个 handoff 阻止其余点 |
| F-A2 | 新增 | 新事实只写一条 current canonical truth | 证据 ANSWERED 但内容 task-local 时不得新增 |
| F-A3 | 修订/替换 | 新旧 ID 有 supersede lineage，默认只读新正文 | 不得保留两个互相重叠的 current truth |
| F-A4 | 确认 | 已有 truth 增加确认审计但行数不增加 | 文本略有差异不得自动当新知识 |
| F-A5 | 一次性请求与长期偏好 | F9 分别得到 no_write 与规范化 future behavior | 用户确实说过不能单独证明长期价值 |
| F-A6 | 冲突 | F10 冲突保留审计并阻止 truth mutation | 不得用 provisional 降权掩盖冲突 |
| F-A7 | 幂等 | finalize/replay 的 disposition、truth ID、lineage、Note hash 一致 | 重放不得重复新增或重复 supersede |
| F-A8 | 非法/矛盾候选 | reject 作为独立终态，不写 truth | 不得把 reject 和合法但非长期的 no_write 混为一类 |

### G. 检索使用（0.9.15 目标）

| ID | 场景 | 必须直接证明 | 负例 |
|---|---|---|---|
| G1 | 默认检索投影 | F11 只返回 title、statement 和解释正文所需的 scope/freshness | 不得泄漏 session/job/candidate/evidence ID、hash 或 reason code |
| G2 | 显式审计 | 同一 truth 可按需回查来源、验证、变更和 undo 记录 | 审计附件不得成为第二 truth |
| G3 | 当前版本唯一性 | refine/supersede 后默认只命中 replacement | 旧 current 索引残留即失败 |
| G4 | 确认去重 | confirm 证据不增加搜索命中数 | 同义表达不得占据多个 top-k 槽位 |
| G5 | 状态过滤 | deferred/rejected/provisional/superseded 默认零命中 | 只有降权而仍在默认结果中即失败 |
| G6 | 候选源隔离 | 默认 memory search 只从 current canonical truth 取候选；原文走显式 raw/timeline/observation/audit 路径 | 仅在渲染层隐藏 Observation ID 但仍让 raw 占据 top-k 即失败 |

### H. 受控迁移（0.9.15 目标）

| ID | 场景 | 必须直接证明 | 负例 |
|---|---|---|---|
| H1 | 固定 cohort | preview 绑定 122 个精确 ID、payload hash、project、cutoff 和 cohort fingerprint | 不得用当前 provisional 总数替代固定清单 |
| H2 | cohort 漂移 | 任一 payload/generation 变化或实时条目增加时，旧 manifest apply fail closed | expected=122 而实时不是 122 时不得继续 |
| H3 | 缺失记录 | 当前缺失的 2 个 ID 只有在 event/lineage 给出直接终态证据时才算 accounted | “数据库里没有了”不是成功清理证据 |
| H4 | delta cohort | 新增 archive-derived provisional 按项目授权和 provenance 单独冻结/守恒 | 不得顺带修改其他项目全部 provisional |
| H5 | 中断与索引 | canonical commit 前可回滚；commit 后 derived index 可从 canonical 重建 | 索引成功不能掩盖 canonical 部分写入 |
| H6 | rollback | 仅在无后续 generation 时恢复 before-image，恢复后 payload/index/search fingerprint 一致 | 不得覆盖迁移后新增 truth |

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
| 质量 | 预期晋升点召回 100%，禁止长期写入 0，逐点 disposition 100%，Note/truth/检索闭环 100% |

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
3. `tests/test_public_docs_lifecycle.py` 与 MCP surface contract；
4. 全量 pytest；
5. 运行 `.codex/outcomes.json` 中的隔离 outcome probes。

任何 lossless 覆盖、Answer Gate、job 归属、Note hash 或项目隔离失败，立即停止，
不得继续跑昂贵的模型测试。

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

交付列车状态：0.9.13 已加入 F8-F11 shadow fixtures；0.9.14 已加入 F-A1～F-A8
及隔离持久化 outcome probe；0.9.15 将加入 G1～G6、H1～H6。随后在隔离数据目录完成固定 cohort 与 delta cohort
迁移演练，最后用一个新的真实多晋升点 Desktop 会话证明
Hook → job → 逐点验证 → 归纳吸收 → Note → 干净检索。不能用“provider 返回合法 JSON”
或“job completed”代替这个结果。

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

0.9.15 在此基础上增加第五批：受控迁移批。先对审计清单中的固定 122 个 ID 生成
content-addressed dry-run disposition 清单，解释当前缺失项，并将迁移期间新增的授权
archive-derived delta 单独冻结和守恒；隔离回滚演练通过后才应用真实迁移。随后从正常
search 路径逐条回读保留/替换结果，并验证 reject/supersede/provisional 在默认检索中
零命中。

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
