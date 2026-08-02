# LoCoMo

- 定位：长多会话对话数据集与离线问答评测，不是可部署的 memory store。
- 上游：<https://github.com/snap-research/locomo>
- 本地镜像：`F:\\AIInfra\\upstreams\\harness-mem\\locomo`
- 复核基线：`main` 的 `3eb6f2c585f5`（2026-08-01）；没有 release tag。

## 架构与数据流

```text
多日对话会话 + 时间标记
  -> session summary / dialogue context
  -> QA question + gold answers
  -> normalized EM/F1 evaluation
```

数据集把一个长对话拆成多个带日期和事件的 session；评测脚本先生成或读取
session summary，再将问题、上下文和多答案 gold 交给离线评分器。它的价值在于
给检索系统提供跨 session、时间事实和更新事件的固定输入，而不是提供存储、租约或
删除语义。

## 状态与评测语义

- session 是输入边界；summary 必须保留双方事实和时间关系。
- QA 评分会 normalize 答案，并对多个 gold answer 取最大匹配的 EM/F1。
- 当前实现没有一等 `unanswerable`/abstention 结果；空答案不能直接被当作
  harness-mem 的正确拒答。

## 可复核证据

| 主题 | 本地源码证据 | 结论 |
|---|---|---|
| Summary 输入契约 | `F:\\AIInfra\\upstreams\\harness-mem\\locomo\\task_eval\\get_session_summaries.py:28-47,84-91` | summary 需要保留人物事实与日期上下文。 |
| 多答案评分 | `F:\\AIInfra\\upstreams\\harness-mem\\locomo\\task_eval\\evaluation.py:126-145,189-214` | normalize 后按答案集合取最大匹配。 |
| 数据/任务结构 | `F:\\AIInfra\\upstreams\\harness-mem\\locomo\\README.md` 与 `data` fixtures | 适合作为跨 session replay 输入，不是 runtime API。 |

## 对 harness-mem：adopt / adapt / reject

**Adopt**：跨 session 的时间事实、会话摘要和知识更新 fixture 形态。

**Adapt**：把每个问题绑定到 source revision、gold IDs、检索结果和 abstention
reason；使用 LongMemEval/MemoryData 的显式拒答语义补足 LoCoMo 的缺口。

**Reject**：把 F1 当作唯一产品指标，或把数据集的 summary prompt 直接变成生产
Dream 规则。

## 影响版本

`0.9.7` 使用 LoCoMo 形状扩充跨 session/时间推理 golden；`0.9.9` 用同样的
session replay 结构验证七宿主的真实 transcript 适配。验收要求不可回答问题仍有
明确 abstention，而不是“没有命中所以通过”。
