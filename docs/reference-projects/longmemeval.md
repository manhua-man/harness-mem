# LongMemEval

- 定位：长会话中“检索覆盖、最终任务答案、不可回答识别”三条分离指标的参考 benchmark。
- Upstream：<https://github.com/xiaowu0162/LongMemEval>
- 本地镜像：`F:\AIInfra\upstreams\harness-mem\LongMemEval`
- 已核验 HEAD：`9e0b455f4ef0e2ab8f2e582289761153549043fc`（2026-08-01）。

## 架构与数据流

LongMemEval 有意拆开 retrieval 和 answer evaluation。retrieval runner 选择 session 或 turn 粒度、BM25/dense/oracle retriever，并可用 session summary、keyphrase、user fact 等 index expansion；其扩展结果可以缓存，避免把扩展模型的随机性混入每次检索比较。

输出的 retrieval results 包含候选和 metrics；随后 generation/answer 结果按 `question_id` 与 reference 对齐，由单独 evaluator 判定。因而失败可被定位为“证据没召回”“证据召回但回答失败”或“模型没有正确拒答”，而不是一个不可解释的单总分。

## 状态、评测与错误语义

- QA judge 对 single-session、multi-session、temporal reasoning、knowledge update、preference 使用不同 correctness prompt；knowledge update 允许模型同时提及旧信息，只要更新答案正确。
- question ID 含 `_abs` 时切换到 unanswerable 判定：正确答案是识别信息不完整/不可回答，不是编造一个空答案。
- 汇总同时给 task-averaged accuracy、overall accuracy 和 abstention accuracy；检索则按 session/turn 独立报告 `recall_all` 与 `ndcg_any` 的多个 cutoff。
- 上游 judge 是 LLM 调用，因此其绝对 answer score 不能作为本项目 CI 的确定性门槛；应借用分类与分报，不复制有外部模型依赖的裁判。

## 可复核证据

| 结论 | 本地源码证据 |
|---|---|
| QA evaluator 根据 task 与 abstention 构造不同 judge prompt | `F:\AIInfra\upstreams\harness-mem\LongMemEval\src\evaluation\evaluate_qa.py:24-55` |
| `_abs` question ID 启用不可回答评测 | `F:\AIInfra\upstreams\harness-mem\LongMemEval\src\evaluation\evaluate_qa.py:101` |
| 汇总 task、overall 和 abstention accuracy | `F:\AIInfra\upstreams\harness-mem\LongMemEval\src\evaluation\print_qa_metrics.py:16-33` |
| session/turn retrieval 分别报告 recall-all 和 nDCG | `F:\AIInfra\upstreams\harness-mem\LongMemEval\src\evaluation\print_retrieval_metrics.py:30-43` |
| `recall_all` 要求所有 gold documents 被召回 | `F:\AIInfra\upstreams\harness-mem\LongMemEval\src\retrieval\eval_utils.py:27-29` |
| retriever、粒度和 index expansion 是独立实验参数 | `F:\AIInfra\upstreams\harness-mem\LongMemEval\src\retrieval\run_retrieval.py:24-57` |
| cached expansion 被显式加载并用于检索 | `F:\AIInfra\upstreams\harness-mem\LongMemEval\src\retrieval\run_retrieval.py:232-264,351-363` |

## 对 harness-mem 的取舍与版本影响

**Adopt，目标 `0.9.7`：** 将评测报告固定为三条分数线：检索 coverage、任务/上下文充分性结果、abstention。fixture 至少包含单跳、跨 session 合成、时间推理、知识更新、偏好、无证据和 temporal conflict 七类；时间题必须记录 `as_of` 和 source validity。现有 `no_evidence`、`temporal_conflict` abstain 语义保留，不把无命中显示为低置信“答案”。

验收：每类均有确定性本地 fixture；报告同时打印每类和总体；无证据/冲突样本的 abstention precision、recall 可计算；检索 coverage 与 answer/context 结果可独立失败；CI 不请求 OpenAI 或任何 judge 模型。

**Adapt，目标 `0.9.8`：** 允许在离线实验中比较 raw turn、session summary 和提取式 keyphrase 三种 retrieval representation，但必须锁定相同 corpus、top-k、token 预算和 seed，并把扩展来源写入 trace。不要让摘要替代原始 evidence/provenance。

**Reject：** 依赖 LLM judge 的 release gate、把 `_abs` 仅编码在字符串 ID 中、以及把 oracle retrieval 作为真实产品质量。它们分别损害可重复性、可读性和外部有效性。
