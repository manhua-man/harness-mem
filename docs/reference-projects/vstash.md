# vstash

- 定位：论文级研究观察，不是已验证的实现或依赖。
- 论文：<https://arxiv.org/abs/2604.15484>
- 本地实现：无；`F:\\AIInfra\\upstreams\\harness-mem` 下没有权威源码镜像。
- 复核标记：arXiv v1（2026-04-16）。

## 证据边界

当前可引用的只有论文方法和实验描述，不能把论文中的 adaptive RRF、distance
confidence 或 post-fusion reranking 当作已有 API、可复现性能或版本依赖。没有源码、
固定 fixture 和失败语义之前，也不能把它列入 release gate。

## 对 harness-mem 的观察项

- 观察 adaptive RRF 是否在 harness-mem 的 retrieval-isolated fixture 上稳定优于
  当前确定性排序。
- 观察距离置信度是否能改善 abstention，而不是只提高命中率并增加误召回。
- 观察 post-fusion reranking 的成本、可重复性和跨项目隔离风险。

## 影响版本

目前不进入 0.9.7-0.9.9 的实现范围。只有出现权威实现、可复现实验和明确的本地
fixture 后，才触发一次实验性 A/B 评测；在此之前不改默认 RRF、不增加配置项、不引入
新的索引后端。
