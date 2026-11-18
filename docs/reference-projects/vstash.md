# vstash

- 定位：本地向量、全文及混合检索的研究参考，不是 harness-mem 的运行依赖。
- 论文：<https://arxiv.org/abs/2604.15484>（arXiv v1，2026-04-16）。
- 上游源码：<https://github.com/stffns/vstash>；2026-11-04 对照固定提交 `4c63cf5395eb9a9ee7a279a52cb584e2874d4ab3`，MIT。
- 本轮临时克隆：`.tmp/recall-quality-20261103/vstash-upstream`；不在正式参考镜像目录中，也未安装。

## 已核对的实现及边界

此前将该项目写成只有论文是不准确的，上游现有公开源码。固定提交的
[`store/__init__.py`](https://github.com/stffns/vstash/blob/4c63cf5395eb9a9ee7a279a52cb584e2874d4ab3/vstash/store/__init__.py#L1668)
使用空格拆分后的词数判断长查询，
[`store/_schema.py`](https://github.com/stffns/vstash/blob/4c63cf5395eb9a9ee7a279a52cb584e2874d4ab3/vstash/store/_schema.py#L78)
的 FTS 索引使用 `porter ascii`。因此不能直接把它的长查询启发式当作中文长请求处理。

[`services/search.py`](https://github.com/stffns/vstash/blob/4c63cf5395eb9a9ee7a279a52cb584e2874d4ab3/vstash/services/search.py#L159)
在调用 store 之前生成查询 embedding，选择 `fts_only` 也会经过这一步；包要求 Python
`>=3.10`，而本项目支持 `>=3.9`。这只是对静态实现的检查，没有运行上游完整检索路径，
不能推断其在本项目数据上的速度、精度、隐私配置或故障表现。

## 对 harness-mem 的取舍

- 保留自适应融合、距离阈值及后续重排作为可对照的研究主题；不能把非空向量结果
  当作当前任务的相关性证明，也不能直接迁入另一套索引或服务。
- 本轮关注候选发现、预算内选读以及正反例评测；现有源码尚无 vstash 融合实现。
- 只有在固定源码和模型、补齐中文及无答案样本、量化维护与查询成本后，才有条件
  决定是否做进一步 A/B；不把论文或参考排名写成已验收的产品能力。
