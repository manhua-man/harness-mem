---
name: distill
description: 用户要求整理已结束的对话、从历史对话保存有来源的长期知识，或接着整理上次中断的会话时使用。
---

# Distill

当前 Agent 完整阅读会话、核对证据、决定值得保存的内容。Python 运行时管理来源版本、分段进度、事务和回读。用户只需描述要整理哪段对话；Agent 自行使用下列 Python 接口，保管批次引用和证据参数。全程使用当前宿主的执行能力。

## 读取与恢复

1. 在有本项目 Python 包的解释器中导入 `from harness_mem.distill import Distill`，建立 `d = Distill()`。一次整理始终使用同一个数据目录。
2. 用 `d.sessions(project_root=当前工作区绝对路径)` 盘点。跨项目查找可省略 `project_root`。按用户所指的宿主、时间和内容定位返回的行，需要辨认来源时用 `d.source(session=行, offset=位置)`。多个来源均符合且无法判定时，用会话主题让用户选择。
3. 新批次调用 `d.prepare(sessions=选中的行列表)`，保存返回的 `batch_id`。同一次整理后续都用 `d.prepare(batch_id=原批次)`。恢复时若当前对话没有保留批次引用，查看 `d.sessions()`（项目批次带原项目范围）中的已有批次，按冻结范围和进度辨认。
4. 每次读取返回的 `chunks` 中每段完整 `raw_content`，按 `chunk_index` 记录可能对将来有用的知识点、纠正、证据位置和待办。读完一段才调用 `d.checkpoint(job_id, chunk_id, packet["lease_owner"], {"summary": 实际阅读笔记})`，其中 `job_id = packet["distill_job_id"]`。用原批次继续直到 `distill_status == "reviewing"`。这时 `chunk_results` 包含先前的阅读笔记。被中断且尚未提交的读取可以使用原租约继续；租约失效后重新领取未完成段。
5. 用户要求暂停时调用 `d.prepare(batch_id=原批次, pause=True)`。收到继续请求后使用 `continue_batch=True`；自然中断后直接用原批次。查看失败原因，按返回结果决定是否显式重试。检测到版本或授权变化时报告受影响的范围。

## 判断与提交

- 对照准备结果中的 `current_knowledge` 和模块目录，按需调用 Search 查同主题的完整旧正文。每个点只保留一个可独立回答以后问题的事实，写清仍适用的条件、日期、例外或未定状态。一次性过程进会话总结，真实未完成动作进 `unfinished_work`。
- 在审阅阶段用 `d.read(job_id, exchange_indexes=[交换序号])` 核对含角色、原文和摘要的证据窗口。技术事实核对当前文件或实际返回结果；明确区分用户决定、助手报告、已观察到的操作。Codex 准备结果中若提供原生阅读问题，取 `packet["native_evidence"]["review_questions"]["arguments"]["native_evidence"]` 交给 `d.read(job_id, native_evidence=请求)`；同理用 `read` 请求查有关操作记录。按 `next_offset` 继续读至所需记录完整，证据不足的范围保留说明。
- 取 `packet["finalize_contract"]["args_template"]` 作为填表参考，用实际内容替换示例。每个写入点填写标题、正文、模块、处置、证据依据及核验结果。`verification_refs` 使用原文窗口的交换序号、角色和 `content_sha256`；`review.evidence` 的 `ref` 及相应角色内的 `message_index` 均从 1 开始，`quote` 必须是可定位的原句。补充、确认或替换时带入准确的旧条目。缺少证据或没有独立长期用途的点可不写。
- 由 Agent 填写会话总结、最后用户要求、实际结果、证据覆盖及遗留事项。调用 `d.finish(job_id, semantic_review=会话审阅, memory_points=各点)`。未通过时按具体错误回查来源或修正判断。收到变化和回读结果后再向用户报告保存的内容及剩余问题。多场会话继续用原批次处理下一场。
- 结果提供 `resume_deferred` 且用户要求重审时，用 `d.revisit(job_id)` 找回原来源的未解决点。用户要求清理已处理原文时先用 `d.cleanup(batch_id)` 核实冻结批次、保留成果和删除范围。明确授权物理删除后才用 `d.cleanup(batch_id, apply=True)`。平时整理保留原文。
