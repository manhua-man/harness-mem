# harness-mem Benchmark System

## 目标

这份文档定义 `harness-mem` 自己的 benchmark 体系，用来回答三个不同层面的问题：

1. 当前改动是否让系统变好或变坏。
2. 产品主链路是否真的比“只会检索 transcript”更强。
3. 对外时，哪些结果可以叫 benchmark，哪些只能叫工程评测或实验脚本。

这份文档的核心原则是：**外部 benchmark 用来对齐行业坐标，内部 benchmark 用来指导产品演进。**

---

## 三层定义

### Layer 1: Experiment Script

这是快速实验脚本，用来验证某个 retrieval 想法有没有信号。

当前仓库里的代表是：

- `harness_mem.tools.longmemeval`

它的定位不是“正式 benchmark 系统”，而是：

- 快速试错
- 观察 retrieval recall 变化
- 对比 raw / hybrid / rerank 等候选方案

它的已知限制包括：

- 使用简化版 `BenchVerbatimStore`，没有完全走正式 runtime
- 当前只测 retrieval，不测 end-to-end answer quality
- 当前语料构建是 session 级拼接，不等同于真实产品里的 dual-layer memory
- 当前没有覆盖 wake-up、task resume、learning loop、abstention

结论：**Experiment Script 可以指导迭代，但不能单独代表产品 benchmark。**

### Layer 2: Engineering Eval Suite

这才是 `harness-mem` 自己的 benchmark 主体。

它的要求是：

- 尽量走真实 runtime 路径
- 尽量覆盖真实产品能力，而不只测某一个 retrieval 函数
- 每次迭代都能稳定复跑
- 输出可以直接指导 roadmap 和回归判断

这层是 `harness-mem` 自己最该长期维护的 benchmark。

### Layer 3: External Benchmark Anchors

这是对外比较用的公开 benchmark，用来回答“我们和行业公开结果差多少”。

对 `harness-mem` 来说，外部 benchmark 的定位不是替代内部 benchmark，而是作为锚点：

- LongMemEval：当前主 benchmark
- LoCoMo：下一阶段重点补充
- ConvoMem：后续补充 preference / implicit connection / early-stage memory 策略
- Mem-Gallery：以后如果做多模态再考虑

结论：**外部 benchmark 决定外部坐标，内部 benchmark 决定产品方向。**

---

## harness-mem 自有 benchmark 范围

`harness-mem` 的 benchmark 不应该只测“能不能把正确 session 找回来”，还应该覆盖它作为 memory runtime 的核心能力。

### 1. Retrieval Benchmark

回答的问题：

- 能不能从大量历史中找回相关记忆
- 不同 retrieval 策略是否真的提高 recall
- 哪些类别仍然存在明显短板

建议评测维度：

- `R@5 / R@10 / R@20`
- `MRR`
- `zero-recall rate`
- per-type recall
- latency per query

建议评测视角：

- `user-only`
- `assistant-only`
- `full-session`
- `verbatim-only`
- `structured-only`
- `hybrid`

这部分的作用是回答：**检索底座是否变强。**

### 2. Wake-up Benchmark

回答的问题：

- 新会话开始时，`wake-up context` 是否真的把有用背景带出来
- 在有限 token 预算内，是否能覆盖关键上下文
- 是否出现明显错误注入或无关注入

建议评测维度：

- support recall
- irrelevant context rate
- wake-up token size
- human spot-check pass rate

这部分的作用是回答：**轻量注入是否有效。**

### 3. Task Resume Benchmark

回答的问题：

- handoff 是否能恢复工作状态
- next step 是否正确
- blocker / task status 是否可用

建议评测样例：

- 单任务中断恢复
- 多任务并行切换
- 隔天恢复
- 跨客户端恢复

建议评测维度：

- resume success rate
- correct next-step rate
- task-state fidelity

这部分的作用是回答：**系统是否不仅能“找历史”，还能“续工作”。**

### 4. Learning Loop Benchmark

回答的问题：

- correction -> candidate rule -> confirm 是否形成有效闭环
- 规则保存后，是否真的降低重复错误

建议评测维度：

- candidate precision
- acceptance rate
- post-confirm error recurrence
- rule recall hit rate

这部分的作用是回答：**系统是否真的在学习，而不是只在记日志。**

### 5. Local Mode Benchmark

回答的问题：

- 在纯本地模式下，系统是否足够快、足够轻
- 索引、查询、存储增长是否可接受

建议评测维度：

- ingest throughput
- query latency
- cold-start latency
- disk growth
- memory usage

这部分的作用是回答：**local-first 是否只是口号，还是工程上成立。**

---

## 外部 benchmark 的使用策略

### 1. LongMemEval

定位：当前主 benchmark。

用途：

- 继续作为 retrieval 主 benchmark
- 重点盯 `multi-session`、`temporal-reasoning`、`preference-like` 类型
- 作为 V1 到 V1.x 的主要对外参照

依赖：

- 从源码树直接运行 benchmark 时不需要安装独立工具包，使用 `python -m harness_mem.tools.longmemeval ...` 即可。
- clean env 需要安装 benchmark extra：`pip install -e ".[benchmark]"`。
- 若使用真实 hybrid / vector 路径，再同时安装 hybrid extra：`pip install -e ".[benchmark,hybrid]"`。

注意：

- LongMemEval 结果只能说明长期记忆检索能力，不等于整个产品已经成立
- 不能把 `python -m harness_mem.tools.longmemeval` 的结果直接包装成完整产品 benchmark

### 2. LoCoMo

定位：下一阶段最该补的外部 benchmark。

用途：

- 验证 `timeline`
- 验证 `task resume`
- 验证长程事件与时间推理

它特别适合回答：**dual-layer memory 是否比纯 retriever 更有上升空间。**

### 3. ConvoMem

定位：中期补充 benchmark。

用途：

- preference
- implicit connections
- early-stage conversation memory strategy

它特别适合回答：**在会话还不够长时，复杂 memory stack 是否真的值得启用。**

### 4. Mem-Gallery

定位：未来多模态扩展 benchmark。

当前先不纳入主线。

---

## 当前 V1 benchmark 的真实定位

截至 V1，仓库里已经有一份对外可读的结果报告：

- `docs/benchmark_v1.md`

这份报告的准确定位应该是：

- `harness-mem` V1 retrieval baseline report
- 基于 LongMemEval 的工程评测结果
- 不是完整的 `harness-mem` benchmark 体系

它的价值在于：

- 给出 V1 的公开起点
- 说明与 MemPalace retrieval baseline 的差距
- 暴露 `multi-session`、`temporal`、`preference` 的核心短板

它不应被过度解读为：

- 完整产品 benchmark
- 最终 retrieval 结论
- 对 V2 能力的直接证明

---

## V1.1 到 V2 的 benchmark 演进路线

### V1.1

目标：把 LongMemEval 从“实验脚本”升级为“更像正式工程评测”。

应完成：

- 跑真实 runtime 路径
- 支持 `user-only / assistant-only / full-session`
- 区分 `verbatim / structured / hybrid`
- 固定输出格式

### V1.2

目标：补足产品主链路评测。

应完成：

- wake-up benchmark
  - 已有 `daily-wake-temporal-safety` 报告型 gate，用固定夹具检查旧但关键的 memory 是否会被最近普通 memory 挤出
  - wake memory selection 采用“最近条目 + 重要性保护”，避免纯 recency 选择
- task resume benchmark
- learning loop benchmark
- local mode benchmark

### V2

目标：形成完整 benchmark 套件。

应完成：

- LongMemEval 作为 retrieval 主 benchmark
- LoCoMo 作为长程事件/时间 benchmark
- ConvoMem 作为 preference / implicit connection benchmark
- internal engineering eval suite 稳定化

---

## 对外表述规范

以后对外时，建议固定用下面三种说法，避免混淆：

### 可以说

- `LongMemEval retrieval baseline`
- `engineering evaluation`
- `internal benchmark suite`
- `wake-up/task-resume evaluation`

### 不建议直接说

- `our benchmark proves the product is better`
- `this script is the full benchmark`
- `retrieval score equals product capability`

---

## 一句话结论

`harness-mem` 自己的 benchmark 不应该只是一份 LongMemEval 脚本，而应该是一套覆盖 retrieval、wake-up、task resume、learning loop、local mode 的工程评测体系；LongMemEval、LoCoMo、ConvoMem 则是这套体系对外对齐行业坐标的锚点。
