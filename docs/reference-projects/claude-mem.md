# claude-mem

- 定位：面向编码 Agent 的会话观察、检索与生成服务；本页只把它作为产品运行时可靠性参考。
- 上游：<https://github.com/thedotmack/claude-mem>
- 本地镜像：`F:\AIInfra\upstreams\harness-mem\claude-mem`
- 复核基线：`main` 的 `a90066f9cf82cc936dd2d841319bb6b19658f7d4`（2026-08-01 本地核查）。

## 定位与边界

claude-mem 的 server-beta 路径将 HTTP 事件接收、Postgres 持久化、Redis/BullMQ
传输和 observation generation worker 分开。它适合回答“在外部消息 broker 不可用、
worker 重启或端口被占用时如何保住工作”，不适合成为 harness-mem 的默认架构：后者的
边界是本地 SQLite、既有 distill job、由 Agent 执行语义处理，且不引入 Redis、BullMQ
或常驻第二 worker。

## 运行时组件与数据流

```text
HTTP / compatibility adapter
  -> Postgres transaction: agent_event + generation_job(outbox) + event log
  -> BullMQ queue (best-effort publish)
  -> BullMQ worker -> provider generation -> Postgres canonical result/audit
```

`IngestEventsService` 先在一个 Postgres 事务中保存 event、generation-job outbox 和
`queued` 生命周期事件；提交后才尝试 `queue.add`。队列解析失败或 `add` 抛错时返回
`queued_only`，而不是回滚已保存的事实。这样，后续 reconciliation 可以从持久 payload
重投，且 HTTP 调用方能区分“已入队”和“只持久化”。

`ServerJobQueue` 将 BullMQ 封装为一个命名 queue/worker 对：worker 以
`autorun: false` 建立、显式 `run()`，默认并发为 1；worker 与 `QueueEvents` 都报告
stalled/error，并对重复 stalled 通知做短窗口去重。关闭顺序为 QueueEvents、worker、
queue，尽量关闭全部资源并在最后报告第一个错误。

## 存储与状态模型

- Postgres outbox 是 generation job 的规范历史；BullMQ 的 completed/failed 状态只是
  执行传输状态，不能被当作审计事实。
- 每个 event job 有稳定的 `bullmqJobId` 和持久 payload；同一个 logical job 可安全被
  reconciliation 再次提交。
- 默认传输策略是 3 次、5 秒起步的指数退避；completed 保留 7 天/最多 1000 条，failed
  保留 30 天/最多 1000 条。因此它有可观察的近期失败窗口，但不是无限期队列审计。
- 本地 SQLite `SessionStore` 仍承担较旧的 session/observation 路径；构造时执行一组
  versioned schema 修补，部分表重建在显式事务中回滚。

## 任务、删除与恢复链路

任务链路的关键是 **transactional outbox + post-commit publish**，而非“先投递再补写
数据库”。队列端可见等待、活跃、延迟、失败和完成计数；运行期另记录 stalled/error
计数，给 health/运营界面使用。`start()` 拒绝重复调用，避免同一进程创建两个消费者。

worker 管理还区分 liveness 与 readiness，并在 Windows 上把 HTTP health probe 的失败
回退到 socket bind 探测；这避免非 HTTP zombie 占住端口时被误判为“端口空闲”。重启/
停止通过显式 HTTP shutdown 路径和“等待端口释放”完成。

这里的删除不是本项目可直接复用的基准：server 的 outbox/事件保留策略与 harness-mem
的隐私擦除、内容无关 receipt、残留验证是不同问题。harness-mem 必须继续把 native
source cleanup 与 truth 删除分开处理。

## 可靠性设计、测试与可观测性

| 主题 | 当前实现与测试证据 | 可复核结论 |
|---|---|---|
| Outbox 事实优先 | `F:\AIInfra\upstreams\harness-mem\claude-mem\src\server\services\IngestEventsService.ts:96-151`；`:226-246` | event/outbox/log 同事务；broker 不可用时保留 `queued_only`。 |
| 传输重试与保留 | `F:\AIInfra\upstreams\harness-mem\claude-mem\src\server\jobs\ServerJobQueue.ts:102-108` | 默认指数退避、有限的 completed/failed 留存。 |
| 生命周期事件 | `F:\AIInfra\upstreams\harness-mem\claude-mem\src\server\jobs\ServerJobQueue.ts:184-353`；`F:\AIInfra\upstreams\harness-mem\claude-mem\tests\server\jobs\server-job-queue.test.ts:163-208` | completed、failed、stalled、error 均有 listener、日志和计数；stalled 去重有测试。 |
| 重复启动与关闭 | `F:\AIInfra\upstreams\harness-mem\claude-mem\src\server\jobs\ServerJobQueue.ts:253-357`；`:358-397`；`F:\AIInfra\upstreams\harness-mem\claude-mem\tests\server\jobs\server-job-queue.test.ts:133-155,210-231` | 显式启动、拒绝双启动；关闭覆盖 worker 与 queue。 |
| 僵尸端口/就绪 | `F:\AIInfra\upstreams\harness-mem\claude-mem\src\services\infrastructure\HealthMonitor.ts:48-116`；`F:\AIInfra\upstreams\harness-mem\claude-mem\tests\infrastructure\health-monitor.test.ts:99-178` | Windows health probe 失败后仍以 socket probe 判定端口占用。 |
| SQLite 兼容迁移 | `F:\AIInfra\upstreams\harness-mem\claude-mem\src\services\sqlite\SessionStore.ts:77-115,201-242`；`F:\AIInfra\upstreams\harness-mem\claude-mem\tests\sqlite\session-store-migrations.test.ts:823-860` | session identity 迁移会事务回滚并保留 observations、summaries、prompts、pending rows。 |

## 对 harness-mem：adopt / adapt / reject

**Adopt**：持久任务状态是事实、执行 transport 不是事实；post-commit 投递失败必须留下
可恢复状态；启动/关闭、liveness/readiness 和 stalled/error 必须分别可观测。

**Adapt**：把 outbox 思想映射到现有 SQLite `distill_jobs` 和 chunk checkpoint：Agent 调用
不能成功时，job/checkpoint 保留可判定的 `retryable`/lease 状态和原因；现有 wake、status、
post-turn maintenance 是其唯一有界调度入口，不引入消息中间件。

**Reject**：Redis/BullMQ、独立生成 worker、以 broker 失败/完成状态取代本地审计、构造时
无预检地串行执行大批 schema 修补。后一类迁移不符合 harness-mem 的 snapshot、staging、
receipt-first 与 fail-closed 约束。

## 影响版本

| 版本 | 采用的具体含义 |
|---|---|
| 0.9.7 | 支持既有的 distill job lifecycle reconciliation：从 checkpoint/lease 真相重算 job 状态，记录进展和恢复原因；不得把一次 Agent 调用失败伪装成任务消失。 |
| 0.9.8 | 只把“事实与执行 transport 分离”映射到 derived-index generation manifest、staging 与原子 active-pointer 切换；中断 build 必须保留旧 generation，不复制 `SessionStore` 的启动时修补模式。 |
| 0.9.9 | 在七 host replay/repair qualification 中区分 adapter capture、ingest、cleanup 和 wake 的 failure artifact；Windows zombie-port 与 readiness 思路可用作 host 安装/重启诊断，不能把健康响应误报为 replay 成功。 |
