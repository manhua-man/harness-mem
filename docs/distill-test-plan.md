# Distill 验收测试计划

## 1. 目标

这份计划验证的不是“代码里存在某个处理函数”，而是用户交给 harness-mem
一个会话后，系统确实完成了以下闭环：

```text
原生会话 → 完整证据覆盖 → 语义判断 → 候选或待办 → finalize
        → Session Note → 可检索记忆或明确的无候选结果
```

测试必须同时回答四个问题：

1. 读全了吗：原始 revision、chunk 顺序、hash 和 exchange 索引是否完整；
2. 判断对了吗：应保留的事实没有漏掉，噪声没有进入长期记忆；
3. 真落地了吗：候选、handoff、Note、receipt、Dream 和检索结果是否可从持久化层读回；
4. 成本可接受吗：记录 Agent 实际收到的完整响应 tokens、模型 tokens 和端到端耗时。

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
| 质量 | 预期候选召回 100%，禁止候选写入 0，Note/receipt/hash/检索闭环 100% |

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
Paths: 24/24 passed
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

统一 runner：

```bash
python -m harness_mem.qualification.distill_acceptance \
  --project-root . \
  --output .codex/distill-acceptance-report.json \
  --model-samples
```

runner 从版本化 F1–F7 catalog 计算输入指纹，逐项执行 A1–E6，并把固定模型样本写入
单独的 `distill-acceptance-report-model.json`。模型调用使用 `tools=[]`、`store=false`
和严格 schema；报告不保存 endpoint、认证 header 或 bearer token。
