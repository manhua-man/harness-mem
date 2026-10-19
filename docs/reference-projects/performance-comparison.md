# 外部性能宣传核对：速度与 token

检查日期：2026-10-15。选择 claude-mem、Mem0、Hindsight 三个最相关项目；先读本目录指定六篇参考，再联网核对一手材料。下文的 claim 是作者声明，源码核对只证明计量边界，不是独立复现实验。本页的文献核对未运行模型、安装软件、下载数据集或读取本机历史、记忆及 `.tmp`；harness-mem 的独立实测另见[本轮受控实验](../performance-20261015.md)。

结论：这些数字分别衡量检索输出、预建记忆后的问答、准确率或局部费用，均不能直接与完整 Codex 流程比较，也不能据此排列各家快慢。完整流程的比较至少须覆盖来源读取、提取、验证、写入、纠正、检索和独立回读；仅测其中一段应明确标注。

后续本机实测（2026-10-16）：[180 场完整构建、纠错与检索对照](../performance-full-lifecycle-20261016.md)已经完成，实际共同模型与相同原文下，HM/CM 固定问答均为 70/70，但 HM 完整建库明显更慢，已报告全流程 token 几乎相同且存在未知 usage。向量/缓存配置未完全控制，独立内容审查也保留风险，不能称严格全默认同条件或整体优势。此后续不改写上文 2026-10-15 文献核对的原分母与“本页未运行模型”边界。

## 宣传数字及其分母

| 项目／版本 | 原宣传数字与比较对象 | 单位、统计口径和成本边界 | 能否直接比较完整 Codex 流程 | 一手来源／检查日期 |
| --- | --- | --- | --- | --- |
| claude-mem，当前读取说明 | 约 10 倍 token 节省，对比先取全部详情的传统 RAG；索引约 50–100、详情约 500–1,000 tokens/条 | 检索返回文本的估算，不是整个 Agent 账单；未给固定模型、数据集、重复次数或置信区间。未把观察生成、索引构建、模型推理和多轮调用费用合并计入 | 否；这里只比较读取内容大小，额外工具往返和 Agent 选择仍有成本 | [README](https://github.com/thedotmack/claude-mem#MCP-Search-Tools)、[搜索说明](https://docs.claude-mem.ai/usage/search-tools)，2026-10-15 |
| Mem0，2025 原论文 v1 | p95 延迟降低 91%、token 成本节省超过 90%，对比 full-context；表 2：总 p95 为 1.440 对 17.117 秒，记忆／上下文 tokens 为 1,764 对 26,031 | 总延迟指检索＋生成答案，不含事先建记忆；token 指检索后供回答使用的上下文，以 `cl100k_base` 计数，不是全链路付费 tokens。表中搜索 p95 单独为 0.200 秒 | 否；不包含写入和维护，且是 LoCoMo 问答，不是原生宿主完整任务 | [论文 §3.2、表 2](https://arxiv.org/html/2504.19413v1)，2026-10-15 |
| Mem0，当前 README 的 2026 新算法／托管平台 | LoCoMo：71.4→92.5，7.0K tokens、延迟 p50 0.88 秒；LongMemEval：67.8→94.4，6.8K、1.09 秒 | 分数对比旧算法；单次检索、top-200。README 未把 token 统计方式、延迟计时终点及完整费用账单逐项定义；含托管平台专有优化，不能视为 OSS SDK 成绩 | 否；不能把此 p50 接到旧论文的 p95，也不能继承旧论文的成本定义 | [当前 README](https://github.com/mem0ai/mem0#new-memory-algorithm-april-2026)，2026-10-15 |
| Hindsight，原论文及当前官方基准 | 原论文 LongMemEval-S：同为 OSS-20B，83.6% 对 full-context 的 39.0%，提高 44.6 个百分点；较大配置 91.4%。当前展示 94.6%。另称 recall 的 LLM 费用为零 | 前者是回答正确率，不是速度；后者只指召回阶段的 LLM 费用，没有对照美元总账。所核对材料没有可用于完整流程对比的统一加速倍数或总 token 节省率 | 否；准确率不等于速度，零召回 LLM 费用也不等于零写入、回答或运行费用 | [原论文表 3](https://arxiv.org/html/2512.12818v1)、[当前基准页](https://benchmarks.hindsight.vectorize.io/)、[费用声明](https://github.com/vectorize-io/hindsight-benchmarks#longmemeval)，2026-10-15 |

## 影响解读的模型、数据与脚本证据

**claude-mem：示例与实测要分开。** 搜索说明的具体例子是 20,000→3,000 tokens，按例内数字计算约 6.7 倍、减少 85%，不是约 10 倍的独立实测依据。渐进读取文档另列 30 对 90 秒的目标示例，没有配套运行样本。[搜索说明](https://docs.claude-mem.ai/usage/search-tools)与[渐进读取说明](https://docs.claude-mem.ai/progressive-disclosure)均于 2026-10-15 检查。

其当前 [TokenCalculator](https://github.com/thedotmack/claude-mem/blob/main/src/services/context/TokenCalculator.ts) 将部分观察字段的字符长度除以常数估算读取 tokens，[常数定义](https://github.com/thedotmack/claude-mem/blob/main/src/services/context/types.ts)为 4，并与 `discovery_tokens` 相减展示节省。这个展示口径不能当作真实 tokenizer 或账单核算；也不能据此断言 README 的全部数字都由该函数生成。两文件检查日期：2026-10-15。

**Mem0：旧论文和新平台必须分列。** 原论文使用 LoCoMo 的 10 场长对话，排除 adversarial 类；语言模型操作使用 GPT-4o-mini，质量以 LLM judge 评价。按表 2 自算，延迟降幅约 91.6%、上下文 token 降幅约 93.2%；同表质量分数为 66.88 对 full-context 的 72.90，因而节省并非同质量保证。[论文 §2–4](https://arxiv.org/html/2504.19413v1)，检查日期：2026-10-15。

当前[公开评测仓库](https://github.com/mem0ai/memory-benchmarks)给出平台 LoCoMo 92.5%＝1,425/1,540，LongMemEval 94.4%＝472/500；BEAM 1M 的 64.1 是平均得分乘 100，通过率另为 70.1%，不能混用。其 [LoCoMo 脚本](https://github.com/mem0ai/memory-benchmarks/blob/main/benchmarks/locomo/run.py)先 ingest，再对 `mem0.search` 单独计 `search_latency_ms`，随后才回答和 judge；因此该字段不含写入、回答及评分耗时。脚本当前回答／judge 默认 GPT-5，而仓库说明仍写 GPT-4o；默认值不能反推宣传运行的精确模型，当前 README 也只笼统说明使用同一模型栈。7.0K 等数字缺少与原始运行计数的明确绑定，本次不补猜。上述仓库及脚本检查日期：2026-10-15。公开框架和自报结果尚不是第三方独立验证，平台专有实现也不因框架公开而成为 OSS 可复现部分。

**Hindsight：质量、召回和系统微基准不是一个结果。** 原论文表 3 为 LongMemEval-S 的 500 题，20B 配置使用 GPT-OSS-20B，judge 为 GPT-OSS-120B；91.4% 配置的记忆栈及 judge 使用 GPT-OSS-120B，最终回答使用 Gemini-3 Pro。§7.3 的检索 token 预算仍是占位符，无法从论文还原准确预算。[原论文](https://arxiv.org/html/2512.12818v1)，检查日期：2026-10-15。

当前 94.6% 的来源可追到官方 [2026-03-23 文章](https://github.com/vectorize-io/hindsight/blob/main/hindsight-docs/blog/2026-03-23-agent-memory-benchmark.mdx)：v0.4.19、单次查询模式；不能移用原论文配置解释新分数。[AMB 说明](https://github.com/vectorize-io/agent-memory-benchmark)分开记录 ingestion 和 retrieval，回答与评分使用 Gemini；[系统性能脚本](https://github.com/vectorize-io/hindsight/blob/main/scripts/benchmarks/run-perf-test.sh)明确使用 mock LLM＋pg0，不能代表真实模型速度。官方[旧基准仓库](https://github.com/vectorize-io/hindsight-benchmarks#model-leaderboard)还区分直接模型提取测试与经 Hindsight API 的质量测试；其中模型吞吐不能冒充完整记忆链路吞吐。以上检查日期均为 2026-10-15。

Hindsight [README](https://github.com/vectorize-io/hindsight#memory-performance--accuracy)称研究合作者已独立复现，但本次未取得并审计独立复现报告及对应运行配置；这里只确认它作过该声明，不把它升级为我们独立证明的结果。零召回 LLM 费用仍不覆盖 retain 的模型工作、向量／重排计算、reflect 回答及数据库运行成本。检查日期：2026-10-15。

## 可借鉴的三个测量方法

1. **分阶段计账，同时保留完整任务总账。** 借鉴 Mem0 的搜索／回答分段和 AMB 的 ingestion 分段：在相同来源、模型、任务及缓存条件下，分别记准备与写入、检索、Agent 往返和验证，再报完整墙钟时间、P50/P95、调用数、失败／重试。token 按实际 tokenizer 或 API usage 区分输入、缓存输入、输出和可取得的推理用量；不可取得项标未知。LLM、embedding 和评分费用分别列出，一次构建供多次查询复用时同时报告构建成本和摊销假设。这里只提出口径，不实施新探针。
2. **把渐进读取当成待验证策略。** 借鉴 claude-mem 的按需展开，用同一组可回答任务比较现有完整事实输出与按需读取；计入索引、详情、分页、重复读取和额外推理，而非只比第一包响应。以事实命中、完整性及纠错成功不下降为前提，观察真实总 token 与耗时，允许短事实直接返回。无需复制对方工具层数或架构。
3. **把检索精度与答案质量分开。** 借鉴 PrecisionMemBench 的必含／禁止／仅含集合、更新与噪声案例，联合比较质量、token 和延迟；有效检索、结构性通过、空结果通过分别计数。[报告代码](https://github.com/tenurehq/precisionMemBench/blob/main/src/utils/buildRetrievalReport.ts)按检索延迟汇总分位数；[adapter](https://github.com/tenurehq/precisionMemBench/blob/main/src/adapters/baseAdapter.ts)的 ingestion 记录会扣除 provider 报告的数据库开销，且索引等待另计，不能直接当完整墙钟时间。[README](https://github.com/tenurehq/precisionMemBench)的供应商结果也不是本项目或统一完整流程的独立证明。三项来源检查日期：2026-10-15；只借测试方法，不引入其数据库、provider 或并行存储。

Letta 的本地参考已读；其[当前 README](https://github.com/letta-ai/letta)已指向另一活动代码库，本页未据旧镜像推导性能，故选上述三家作为本次比较对象（检查日期：2026-10-15）。所有带 `main` 的链接都是可变来源；本页记录检查时声明，原论文固定至明确版本。未发现公开数字或缺少计量定义的地方保持未知，不构成任何一家的性能否定。
