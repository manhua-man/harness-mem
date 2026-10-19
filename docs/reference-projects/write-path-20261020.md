# 写入路径核对（2026-10-20）

本轮核对固定提交的实际实现，未运行外部项目或模型。参考用于修复既有提取、核验、吸收、存储和 Dream 的职责衔接。

| 上游固定版本 | 实现事实 | 本项目采用或判断 |
| --- | --- | --- |
| [Hindsight consolidator](https://github.com/vectorize-io/hindsight/blob/b5d8439c8f1b8aa158f4e8278334066792638543/hindsight-api-slim/hindsight_api/engine/consolidation/consolidator.py) | 629–677 定义新增/更新/删除计划，空数组可无操作；1852–1965 约束目标来自本轮取回窗口；388–453 在同一事务检查保留文本并删除重复项；2195–2230 写前复查来源仍有效 | 借鉴目标绑定和提交时检查。Dream 删除目标与保留项在现有 canonical 事务内一起做 SHA 前置检查；不引入另一套队列、知识库或跨存储见证系统 |
| [claude-mem SessionStore](https://github.com/thedotmack/claude-mem/blob/a90066f9cf82cc936dd2d841319bb6b19658f7d4/src/services/sqlite/SessionStore.ts#L2589-L2708) | 观察与会话进度摘要分表，同一事务存储，按会话及内容哈希约束精确重放 | 支持区分任务记录与持久知识；本项目已存在来源、job、Note 和当前知识，不再增表。其 [code mode](https://github.com/thedotmack/claude-mem/blob/a90066f9cf82cc936dd2d841319bb6b19658f7d4/plugin/modes/code.json#L103-L134) 的持久信号筛选仍主要靠提示，不能作为已经解决语义准入的证据 |
| [Mem0 memory main](https://github.com/mem0ai/mem0/blob/38e47ac2619b625ead46733db081251087f0c64b/mem0/memory/main.py#L913-L1008) | 此提交默认路径按提取条目新增，忽略提取返回的 linked_memory_ids，不能继续沿用旧版 ADD/UPDATE/DELETE/NONE 印象 | 不把该路径当作更新吸收模板。1020–1060 批量写失败后逐项重试并记录异常；1164–1169 仍按准备条目构造 ADD 返回，因此不借用它作落库成功判据。保留本项目事务及真实读回 |

## 本地对应

- 用途准入：`autonomous/models.py`、`provider.py`、`worker.py` 与 `commands/evidence_admission.py`。
- 已核报告更新：`commands/separated_assimilation.py` 和 `storage/knowledge_store.py`。存储层旧的一律禁止前驱条件已改为同一来源账户范围检查，避免上层允许但底层永远拒绝。
- Dream 自动维护：`commands/dream.py` 和 `dream_assimilation.py`，由已有来源核验导出维护动作，移除第二次模型动作裁决。
- 写前事务：`storage/canonical_store.py` 增加只读 SHA 断言，`knowledge_store.py` 在删除重复项时同时绑定目标和保留项版本；确认绑定核验目标版本。

这些是实现与部署范围。未另跑模型测试，未手动触发 Hook/Dream，也未把真实库中的错误授权条目人工删除。实际质量结论需要安装后的自然触发证据，不能从参考实现或静态检查推导。
