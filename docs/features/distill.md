# Distill · 把完结会话整理为当前知识

1. Agent 用 `inspect_sessions` 找到允许处理的会话。只读盘点之后，按用户选择确定来源范围。
2. `prepare_session_distill` 准备单场或用 `batch_sessions` 冻结一批会话。后续用返回的 `batch_id` 恢复原选择。按返回的阅读要求检查完整来源、现有知识及可用的原生执行证据。手工任务由当前 Agent 作语义判断。
3. 将可独立核对的说法分别与原文、说话人、执行结果及当前知识比对。候选可能新增、补充、替换或确认现有知识，也可能作为交接、延后或不写入。逐点核验保留真实的证据缺口。
4. 通过 `finalize_session_distill` 提交审阅结果，按返回的知识变化和未完成事项汇报。源记录和 Note 可用于回查，普通检索从当前知识读取。

**Review。** 从普通检索结果取得旧标题、正文及可选模块，用 `target_knowledge` 定位要纠正的当前知识。目标有歧义或已经变化时，保留原条目并说明待核实之处。独立治理使用 `govern_memory`，已绑定 Distill 的候选由对应任务统一收尾。[治理工具契约](../../code/mcps/harness_mem/tools/govern_memory.json)

**Dream。** 宿主 Hook 接入后台任务，后台处理复用验证和吸收逻辑。可用 `dream_run` 显式执行一轮维护，用 `dream_ledger` 查看记录。已属手工处理的任务由手工流程继续。宿主接入与授权见 [quickstart](../quickstart.md)。

**清理原文。** 在原冻结批次上用 `cleanup_processed` 预览目标。收到物理清理授权后才使用 `apply_cleanup`。执行时重新检查来源版本、权限、任务终态和已保留的整理结果。逐项报告成功或阻塞原因。

**验证入口。** [手工流程测试](../../code/tests/test_manual_session_flow.py) 与 [端到端探针](../../harness_mem/qualification/manual_session_outcome_probe.py) 覆盖准备、收尾和重开读取。0.0.1 在 Windows 隔离环境走过五场手工会话，确定性输入覆盖了保留原文、Note 哈希与重开查询。真实宿主自动触发和模型提取质量要分别验收。

**已知并发问题。** Windows 上同时发布手工批次并尝试后台领取时，组合回归中出现过一次读取批次 JSON 的 `PermissionError`。该次后台领取因异常退出，单独复跑同一竞争用例通过。手工任务并发隔离仍需验证 Windows 文件替换窗口中的读取行为。
