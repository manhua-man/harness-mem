# BEAM

- 定位：长时程 memory system adapter contract、失败归因和可审计实验运行的参考 harness。
- Upstream：<https://github.com/MasterSummer/BEAM-LongHorizonMemBench>
- 本地镜像：`F:\AIInfra\upstreams\harness-mem\BEAM-LongHorizonMemBench`
- 已核验 HEAD：`c3d608d5fc7c6c884b28a73c39c93af47f7ca698`（2026-08-01；software vertical v0.1.0 marker）。

## 架构与数据流

BEAM 把系统被测面收敛到 `MemorySystemAdapter`：initialize/reset/add/search/update/delete。测试 harness 只能经由这个 adapter 读写 memory；可选 session、reflection、forgetting 由 capability mixin 声明。因此同一任务矩阵可以把 no-memory control、flat retrieval、Letta、Mem0 等置于相同可观察行为契约下。

典型数据流为：生成/加载 episode -> 以 user/session 初始化 adapter -> 写入 memory -> 在 checkpoint 检索并运行任务 -> 保存 retrieval trace、task outcome、成本和 drift -> scorecard/qualification report 聚合。失败不是终点：runner 为失败任务写 result/failure row，报告仍可被验证和重新分析；run identity 将输入、数据根和 provider profile 绑定，避免错误恢复到不同实验环境。

## 存储、状态、评测与错误语义

- BEAM 不规定数据库实现，契约只评分外显行为：stable ID、top-k 限制、update 后可见、delete 后不可见、reset 清空、重复 delete 幂等。
- capability 是显式状态。声明不支持的操作必须抛出 `UnsupportedOperation`；该异常记录 warning 后非致命，harness 继续并报告 capability gap，禁止崩溃或静默跳过。
- 评测不只回答分：还包括 retrieval、task score、ROI/cost、memory efficiency、drift、online matrix 与 failure attribution。该丰富度适合研究 harness，但不意味着所有指标都要进入日常 runtime。
- UX/operability 上，CLI 允许 dry run 不带凭据，live execution 有明确 env gate；实验失败仍写 summary 与结构化错误类别。

## 可复核证据

| 结论 | 本地源码证据 |
|---|---|
| adapter 是唯一 memory 读写入口，定义 six core lifecycle methods | `F:\AIInfra\upstreams\harness-mem\BEAM-LongHorizonMemBench\src\lhmsb\adapters\base.py:1-117` |
| capability 包括 sessions/reflection/forgetting | `F:\AIInfra\upstreams\harness-mem\BEAM-LongHorizonMemBench\src\lhmsb\adapters\base.py:42-60,125-167` |
| UnsupportedOperation 是 logged、non-fatal 的降级语义 | `F:\AIInfra\upstreams\harness-mem\BEAM-LongHorizonMemBench\src\lhmsb\adapters\base.py:26-39` |
| shared contract 检查 round-trip、top-k、update、delete、reset 与 capability | `F:\AIInfra\upstreams\harness-mem\BEAM-LongHorizonMemBench\tests\contract\adapter_contract.py:55-270` |
| delete 幂等是明确的单项契约 | `F:\AIInfra\upstreams\harness-mem\BEAM-LongHorizonMemBench\tests\contract\adapter_contract.py:139-148` |
| metrics 与 long-horizon attribution 有独立测试边界 | `F:\AIInfra\upstreams\harness-mem\BEAM-LongHorizonMemBench\tests\metrics\test_retrieval.py`; `F:\AIInfra\upstreams\harness-mem\BEAM-LongHorizonMemBench\tests\longhorizon\test_failure_attribution.py` |
| 失败实验仍写 report 与 failure row | `F:\AIInfra\upstreams\harness-mem\BEAM-LongHorizonMemBench\tests\qualification\test_cli.py:289-355` |
| run identity 被报告、篡改拒绝，且环境变化会变更 identity | `F:\AIInfra\upstreams\harness-mem\BEAM-LongHorizonMemBench\tests\qualification\test_cli.py:234,368-454` |

## 对 harness-mem 的取舍与版本影响

**Adopt，目标 `0.9.8`：** 为现有 local backend 写一个内部行为契约 suite，而非新 public adapter API。最低覆盖：project/session isolation、写入-检索 round trip、update visibility、soft delete 后无检索命中、重复 delete/cleanup 幂等、reset/erase 范围、top-k、temporal filtering 和 provenance 保留。每个断言独立失败并指明违反的行为。

验收：契约在 canonical 与 legacy-reader fallback fixture 均运行；所有删除测试同时验证全文、向量/索引与 regex 路径均不可见；不支持的可选维护动作返回结构化 `unsupported`/reason，绝不抛出未分类异常或伪成功。

**Adapt，目标 `0.9.9`：** 为既有 Doctor/status/recall full response 增加非敏感的 run/trace identity、输入版本、失败类别和 `answered|abstained|degraded|failed` outcome；失败也产生日志/审计行。它是诊断增强，不增加 MCP tool、provider 或持久化根。

**Reject：** 把 BEAM 的多服务 benchmark、外部 agent provider、实验 CLI 或所有 ROI/drift 指标直接产品化。harness-mem 应只吸收其可复核的行为契约和失败语义，保留本地 SQLite/canonical-store 与现有 27-tool 边界。
