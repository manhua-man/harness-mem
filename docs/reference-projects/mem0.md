# Mem0

- 定位：memory SDK 的 scoped deletion、向量存储适配和 SQLite history 兼容性参考。
- 上游：<https://github.com/mem0ai/mem0>
- 本地镜像：`F:\AIInfra\upstreams\harness-mem\mem0`
- 复核基线：`main` 的 `38e47ac2619b625ead46733db081251087f0c64b`（2026-08-01 本地核查）。

## 定位与边界

Mem0 的 OSS `Memory`/`AsyncMemory` 是同步或调用方驱动的 SDK：它可以将 embedding/vector
store、可选 entity store 和本地 SQLite history 组合起来，但没有持久任务队列、claim/lease、
worker restart recovery 或 unattended semantic execution。因此它是删除 API 语义和多 provider
边界的反例/参考，不是 harness-mem 的 distill runtime 蓝图。

## 运行时组件与数据流

```text
Memory API add/update/delete/delete_all
  -> embedding/vector-store operation
  -> SQLite history record
  -> optional entity-store link cleanup
```

单条 delete 先从 vector store 读取 memory，随后删除 vector，再记录一条带 `is_deleted=1`
的 SQLite history，最后尝试清理 entity relation。`delete_all` 强制至少一个
`user_id`/`agent_id`/`run_id` 过滤器；它反复 list 固定大小 batch，逐条调用 `_delete_memory`，
并以 batch ID 组检测 provider 重复返回同页而提前停止。`reset` 则是另一个、明确的全局破坏
操作：重置 history 后删除/重建整个 vector collection。

AsyncMemory 的批量删除并发执行每条删除，`gather(return_exceptions=True)` 使一个 provider
错误不会取消其余删除；这提高了前进性，但也意味着接口可出现“局部失败而整体 success message”。

## 存储与状态模型

- vector store 是 memory 当前内容的主存储；SQLite `history` 记录 ADD/UPDATE/DELETE 的
  审计轨迹，二者之间没有跨 store 事务或 outbox。
- SQLiteManager 用单连接和 thread lock 包住每次 SQLite 事务；history migration 将旧表改名、
  创建新表、复制列交集、删除旧表，并在异常时 rollback。
- reset 和 migration 都是本地数据库层面的操作；provider collection 与 history 的一致性
  不由同一个事务保证，不能给出 harness-mem 所需的 truth/source/index 删除闭包保证。

## 任务、删除与恢复链路

Mem0 没有任务队列、retry schedule、lease、后台 watchdog 或 crash recovery 链路。调用失败
通常直接抛给调用者；LLM provider 的 extraction 错误会被包装/传播，而非误报“没有可写 memory”。
这对 SDK 调用正确性是好属性，但长期无人值守操作只能由宿主自行实现。

删除方面有三个可借鉴的不变量：单条删除先验证 ID；bulk delete 必须显式 scope；bulk list
不得只依赖 provider 的默认 page size。其不该复制的行为同样重要：async bulk delete 遇到一项
失败仍返回 `{"message": "Memories deleted successfully!"}`，没有提供失败 ID、可重试计划或
残留验证。

## 可靠性设计、测试与可观测性

| 主题 | 当前实现与测试证据 | 可复核结论 |
|---|---|---|
| scope 与分页删除 | `F:\AIInfra\upstreams\harness-mem\mem0\mem0\memory\main.py:1861-1913`；`F:\AIInfra\upstreams\harness-mem\mem0\tests\test_main.py:299-312` | `delete_all` 拒绝无过滤器调用，循环分页直到空结果，覆盖超过 1000 条的场景。 |
| 重复页保护 | `F:\AIInfra\upstreams\harness-mem\mem0\mem0\memory\main.py:1892-1905`；`F:\AIInfra\upstreams\harness-mem\mem0\tests\memory\test_decay_usage_notice.py:120-135` | 相同 ID batch 再次出现时停止，防不兼容 provider 导致无限循环。 |
| 单条删除/history | `F:\AIInfra\upstreams\harness-mem\mem0\mem0\memory\main.py:1840-1858,2065-2092` | 先验证 vector record，再删 vector、记 DELETE history，entity cleanup 为 non-fatal。 |
| SQLite 迁移 | `F:\AIInfra\upstreams\harness-mem\mem0\mem0\memory\storage.py:20-109`；`F:\AIInfra\upstreams\harness-mem\mem0\tests\memory\test_storage.py:253-284` | schema migration 在事务/锁内，旧列交集数据会保留。 |
| provider/LLM 错误传播 | `F:\AIInfra\upstreams\harness-mem\mem0\tests\memory\test_main.py:56-80` | extraction provider 不可用会以 `LLMError` 传播，避免与“零事实”混淆。 |
| async 局部删除失败 | `F:\AIInfra\upstreams\harness-mem\mem0\mem0\memory\main.py:3505-3570`；`F:\AIInfra\upstreams\harness-mem\mem0\tests\test_memory.py:960-1003` | 其测试刻意保留其他删除并仍返回成功；这是 harness-mem 必须拒绝的结果语义。 |

## 对 harness-mem：adopt / adapt / reject

**Adopt**：删除需显式 project/scope；分页必须由调用方驱动，不能假设 vector provider 的
默认 page size；检测重复页并留下诊断；对“provider 不可用”与“没有候选/没有事实”使用不同结果。

**Adapt**：把分页/重复页不变量用于现有 privacy erase 和 processed-source cleanup 的计划
执行阶段。每一批仍要写 content-free receipt、记录 planned/actual 数、执行 residual
verification；对于 shared 或 unsafe native container 保持 `unsupported`/`partial_failure`。

**Reject**：将 vector store 与 SQLite audit 的顺序调用包装成“原子删除”；async 局部失败仍报告
全局成功；多 provider runtime 成为默认依赖；用 `reset()` 代替已 scope 的生命周期删除。

## 影响版本

| 版本 | 采用的具体含义 |
|---|---|
| 0.9.7 | 让 deterministic retrieval fixture/report 将“无证据、scoring skipped、provider/fixture error”与低分/成功分开；同时用 recovery 测试维持 delete 相关生命周期状态的可解释性。 |
| 0.9.8 | 将 scoped delete、delete invisibility、idempotent delete、reset isolation 与 unsupported nonfatal result 写成 derived-index rebuild 的 lifecycle behavior contract；删除条目不得在 rebuild/restart 后重现。 |
| 0.9.9 | 在 host adapter-owned cleanup replay 中按 scope 分批执行，并把 deleted、partial failure、unsupported 和残留验证写入 replay failure artifact；不得以一个泛化 success message 掩盖 native-file 失败。 |
