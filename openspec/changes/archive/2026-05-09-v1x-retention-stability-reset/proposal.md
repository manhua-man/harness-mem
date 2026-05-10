# v1x-retention-stability-reset

## 两条主线

| 主线 | 关心问题 | 关键指标 |
|------|----------|----------|
| **用户价值** (CEO/Office Hours/CLI/Design) | 为什么用户今天更愿意继续用 | 行动闭环、可解释性、低摩擦 |
| **工程稳定** (DevEx/Eng/Health/Linus) | 为什么这个仓库明天不会更脆、更乱、更难扩展 | 可测试性、可维护性、CI 覆盖 |

## v1.3-v1.4 核心命题

**先证明用户会留下，再证明系统能撑住。**

V1 不是"功能够多"，而是"可信、可解释、低摩擦"。

## Assumptions（不做）

- 不做 Web UI
- 不扩新 adapter
- 不上 graph memory
- 不上 reranker
- 不接外部向量 DB
- local-first 不变

## v1.x 结束条件

1. 用户可以直接对预算预警采取行动
2. CLI 和 MCP 讲同一套概念和生命周期
3. 所有结构化 memory 都可追溯来源
4. hybrid 检索有明确收益且不破坏 local-first 轻量特性
5. v1.4 结束后代码库比 v1.2.0 更容易测试、扩展、更少静默失败
