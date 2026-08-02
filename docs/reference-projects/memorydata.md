# MemoryData

- 定位：多记忆方法的 benchmark orchestration、逐 query 工件和 LongMemEval 检索桥接参考；不是生产 memory runtime。
- Upstream：<https://github.com/OpenDataBox/MemoryData>
- 本地镜像：`F:\AIInfra\upstreams\harness-mem\MemoryData`
- 已核验 HEAD：`bdbe698f776d921ac791d1b07c0a7fc65a8bb4bb`（2026-08-01）。

## 架构与数据流

MemoryData 的入口根据配置选择 benchmark split、加载数据、标准化输入字段、运行一个方法 adapter，并把结果交给对应 evaluator。其 MemoryAgentBench loader 不把一条会话仅压成一段 prompt：它生成每题 `eval_metadata`，保留 `question_id`、`qa_pair_id`、question type、question date 和 previous event。这使得最终分数可以回溯到单题、时间和数据源，而非只剩聚合均值。

LongMemEval bridge 的另一条数据流为：读取运行结果/检索 debug 输出 -> 用 `question_id` 对齐原始 LongMemEval 金标 -> 将 retrieved paragraphs 与金标 session/turn 对齐 -> 输出逐 query match 与聚合 recall。它适用于“检索是否带回足够证据”的诊断，不能证明最终模型答案正确。

## 存储、状态、评测与错误语义

- 它是 runner，不提供应被 harness-mem 采用的单一 durable truth schema；目录中 vendored 多种 memory 方法正说明 storage 不能与 benchmark 逻辑耦合。
- 评测将 `recall_any@k` 和 `recall_all@k` 区分：前者只要覆盖一个金标，后者要求覆盖全部金标。多跳问题只看前者会夸大有效性。
- 不适用的数据集、缺少检索 debug、或报告生成异常，都应产生带 `status`/`reason` 的 `skipped` 或 `error` 工件；不是把结果归零，更不是静默成功。

## 可复核证据

| 结论 | 本地源码证据 |
|---|---|
| MemoryAgentBench loader 读取问题日期、类型、ID、previous events | `F:\AIInfra\upstreams\harness-mem\MemoryData\benchmark\memoryagentbench\loader.py:158` |
| 每题建立可 replay 的 `eval_metadata` | `F:\AIInfra\upstreams\harness-mem\MemoryData\benchmark\memoryagentbench\loader.py:173-211` |
| 元数据携带 question/QA pair ID | `F:\AIInfra\upstreams\harness-mem\MemoryData\benchmark\memoryagentbench\loader.py:198-205` |
| recall-any 与 recall-all 的定义 | `F:\AIInfra\upstreams\harness-mem\MemoryData\evaluation\longmemeval\memoryagentbench_longmemeval_recall.py:383-394` |
| 不可评分报告有统一 builder | `F:\AIInfra\upstreams\harness-mem\MemoryData\evaluation\longmemeval\memoryagentbench_longmemeval_recall.py:571-593` |
| unsupported/missing/error 路径调用非评分报告 | `F:\AIInfra\upstreams\harness-mem\MemoryData\evaluation\longmemeval\memoryagentbench_longmemeval_recall.py:728-758,922-950` |

## 对 harness-mem 的取舍与版本影响

**Adopt，目标 `0.9.7`：** 为本地 retrieval-isolated fixture 引入每 query 的可重放结果记录：fixture ID、project/session、问题类别、as-of 时间、gold evidence IDs、returned IDs、过滤/排序 trace、metric，以及 `scored|skipped|error` 和 machine-readable reason。聚合输出至少分开 `recall_any@5/@10` 与 `recall_all@5/@10`；不允许用缺失 trace 计算“0 分”。

验收：每个聚合分数可反查全部 query；金标或 trace 缺失时输出 `skipped`/`error` 且总体 coverage 可见；多证据 fixture 能区分 any 与 all；整个 suite 无网络、无 LLM 调用。

**Reject：** 把其多方法 runner、vendored third-party implementation 或多后端配置带入运行时。harness-mem 只需要评测协议和工件纪律，继续以本地 canonical store 为唯一 truth authority。
