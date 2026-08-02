# Hindsight

- 定位：分布式 memory API 的数据库任务队列、worker 恢复与迁移可靠性参考。
- 上游：<https://github.com/vectorize-io/hindsight>
- 本地镜像：`F:\AIInfra\upstreams\harness-mem\hindsight`
- 复核基线：`main` 的 `b5d8439c8f1b8aa158f4e8278334066792638543`（2026-08-01 本地核查）。

## 定位与边界

Hindsight 将异步 retain、batch retain、consolidation 等工作保存于数据库的
`async_operations`，由可横向扩展的 poller 领取执行。它是本次三个参考中最完整的
无人值守任务模型，但产品边界比 harness-mem 更宽：有常驻 API/worker、Postgres/Oracle、
多租户 schema、LLM provider 和指标服务。harness-mem 应学习其状态机与恢复不变量，
不能因此增加常驻 server、scheduler 或后台语义 distill worker。

## 运行时组件与数据流

```text
API submit -> async_operations(status=pending, payload, operation_id)
  -> WorkerPoller claim -> background task / MemoryEngine executor
  -> completed | pending(next_retry_at) | failed
  -> parent batch aggregation + metrics/status API
```

poller 在每轮按 tenant schema 扫描 pending work，依据 reserved/shared slot 容量领取；
数据库侧使用 `FOR UPDATE SKIP LOCKED`，因此多个 worker 不会领取同一行。领取结果注入
`operation_id`、`retry_count` 和数据库权威的 operation type；运行期本地记录 active task、
阶段、开始时间和每种 type 的 in-flight 数量。

任务执行有三类结果：正常返回后 only-if-processing 地标为 completed；`RetryTaskAt` 将
任务退回 pending 并记录 `next_retry_at`、增量 retry_count；`DeferOperation` 也退回
pending，但不消耗重试预算。未分类异常或 retain 的任务级墙钟超时成为 failed。父 batch
在子任务均 terminal 后以锁保护地汇总为 completed 或 failed，并保留代表性子错误。

## 存储与状态模型

- `async_operations` 是任务和 operation status 的唯一持久权威；worker 内存集合只用于
  当前进程的 slot/accounting 和诊断。
- crash recovery 仅处理本 worker ID 遗留的 `processing` 工作：低于 recovery budget 的
  行改回 pending 并增加 retry_count；达到预算的行变为 failed，避免“领取—崩溃—无限重放”。
- retain 的墙钟超时覆盖整个 executor，而不只覆盖单次 LLM 或 SQL 调用；错误消息携带当时
  stage，以便定位卡死点。
- Alembic migration 对 Postgres 使用 schema-specific advisory lock，同时在进程内用
  threading lock 串行化 Alembic；已比本代码更新的 revision 在滚动发布时视作安全跳过。

## 任务、删除与恢复链路

启动 poller 时先运行 `recover_own_tasks()`，随后进入 claim loop。正常 shutdown 先发出
停止信号、等待 active tasks（默认 30 秒）；逾期后取消其余 task。恢复还包含 batch API
operation 与 orphaned batch parent reconciliation，避免子任务已终态但 parent 永久卡在
`processing`/unclaimable 的状态。

删除/生命周期面，Hindsight 的 operation 记录提供可查询的 terminal error，并让外层 API
决定何时 retry/cancel；这比“删除一个记忆后立即宣称全部关联资源已清理”更稳妥。它并不是
harness-mem 隐私擦除的实现参考：后者必须保持 selector、计划、receipt、CAS/quiet-source
检查、残留验证和 shared-container 不删除的现有边界。

## 可靠性设计、测试与可观测性

| 主题 | 当前实现与测试证据 | 可复核结论 |
|---|---|---|
| 并发领取 | `F:\AIInfra\upstreams\harness-mem\hindsight\hindsight-api-slim\hindsight_api\worker\poller.py:392-545` | `FOR UPDATE SKIP LOCKED` 加 slot reservation/shared pool，防重复领取且减少任务类型饥饿。 |
| 完成/重试/失败 | `F:\AIInfra\upstreams\harness-mem\hindsight\hindsight-api-slim\hindsight_api\worker\poller.py:554-581,694-849` | completed 仅从 processing 转换；retry 与 intentional defer 语义不同；异常有明确 terminal state。 |
| 卡死防护 | `F:\AIInfra\upstreams\harness-mem\hindsight\hindsight-api-slim\hindsight_api\worker\poller.py:33-74,756-838`；`F:\AIInfra\upstreams\harness-mem\hindsight\hindsight-api-slim\tests\test_worker_wall_timeout.py:82-166` | retain task 超时会取消 executor、释放 slot、把 stage 写进 failed reason。 |
| 崩溃恢复/预算 | `F:\AIInfra\upstreams\harness-mem\hindsight\hindsight-api-slim\hindsight_api\worker\poller.py:862-967`；`F:\AIInfra\upstreams\harness-mem\hindsight\hindsight-api-slim\tests\test_worker.py:1150-1440` | processing 遗留任务有限次复原；超限失败并推进父任务，避免无限 crash loop。 |
| 优雅停止 | `F:\AIInfra\upstreams\harness-mem\hindsight\hindsight-api-slim\hindsight_api\worker\poller.py:1238-1274` | shutdown 有等待上限，超限才取消剩余 active tasks。 |
| 多副本迁移 | `F:\AIInfra\upstreams\harness-mem\hindsight\hindsight-api-slim\hindsight_api\migrations.py:20-37,250-378`；`F:\AIInfra\upstreams\harness-mem\hindsight\hindsight-api-slim\tests\test_alembic_dag.py:1-120` | 进程锁+advisory lock 防止迁移竞争，并处理 rolling deployment 的未知新 revision。 |

## 对 harness-mem：adopt / adapt / reject

**Adopt**：以持久状态为准的 claim/lease/recover 模型；任务级而非单请求级的超时；有限的
恢复预算；child/parent 或 chunk/job 终态收敛；进展、stage、retry-at 与 terminal reason
的可观测性。

**Adapt**：harness-mem 已有 SQLite `BEGIN IMMEDIATE`、chunk lease、retry backoff 和
Agent-active lane。0.9.x 应在该单库模型中补足 job-level reconcile：检查 expired lease，
按 checkpoint 重算 `processing`/`reviewing`，记录 last-progress/recovery count，且把重复
恢复超过预算的 job 转为可解释 failed。恢复只能由已有 wake/status/post-turn maintenance
有界触发，不宣称没有 Agent 时仍会自动做语义处理。

**Reject**：常驻分布式 worker、Postgres/Oracle 多后端、第二 scheduler、把 Hindsight 的
operation API 变为新 MCP surface；以及自动执行基础设施破坏性迁移。特别是
`migrations.py` 的 pgvector relocation 路径会调用 `DROP EXTENSION vector CASCADE`
（`F:\AIInfra\upstreams\harness-mem\hindsight\hindsight-api-slim\hindsight_api\migrations.py:62-137`），
绝不能作为本地默认修复策略。

## 影响版本

| 版本 | 采用的具体含义 |
|---|---|
| 0.9.7 | 落地既有的 distill job crash/lease reconciliation 与 recovery budget；job/chunk 不可无限保持 `processing`，也不可无限 retry。故障理由必须指向最后阶段或 lease/recovery 原因。 |
| 0.9.8 | 将 Hindsight 的“旧事实仍可用、失败不切换”原则用于 derived-index staging、atomic activation 与 restart recovery 的 failure injection；Doctor 只分类/建议，不自动 apply destructive repair。 |
| 0.9.9 | 在七 host replay 中用 run identity、source revision、capability set 与 failure artifact 记录 interrupted cleanup/retry；bounded retry 的含义是 partial failure 可见且可重试，不把缺少 Agent/host capability 掩盖为成功。 |
