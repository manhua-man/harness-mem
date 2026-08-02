# sqlite-vec

- 定位：SQLite 向量虚表、KNN 查询规划和向量物理布局的参考；不是 harness-mem 的
  canonical data model。
- Upstream：<https://github.com/asg017/sqlite-vec>
- 本地镜像：`F:\AIInfra\upstreams\harness-mem\sqlite-vec`
- 已核验 HEAD：`04d28bd21773981e2d266bbf6aa4efbd011eb4f6`（2026-08-01）。

## 架构与数据流

`vec0` 把一个逻辑向量表拆成受 SQLite 事务保护的 shadow tables：chunk 表保存 size、
validity bitmap 和 rowid blob；rowid 表把逻辑 ID 映射到 `(chunk_id, chunk_offset)`；
vector、metadata、auxiliary 列分别存放。查询规划由 `xBestIndex` 选择 full scan、point
lookup 或 KNN；KNN 的 query vector、`k`、rowid IN、partition key 与 metadata constraint
被编码为传给 `xFilter` 的参数。

运行数据流为：写入分配/重用 chunk slot -> 更新 rowid 映射、validity、vector 与 metadata
blob -> KNN 根据 plan 遍历有效 chunk、应用 partition/metadata filter、维护 top-k rowids /
distances -> 返回逻辑 rowid。这个设计强调“派生数据的多份物理表示必须同步”，而不是
要求 harness-mem 接触 sqlite-vec 私有表。

## 索引、更新、删除与故障语义

- 检索模型：KNN 在 chunk 上迭代，能够将 metadata/partition 约束放在候选过程，而不是
  全量近邻返回后才做无遮罩的应用层筛选。
- 更新/删除：删除会移除 rowid 映射、清空 validity 位和 vector/rowid blob slot；清空整个
  chunk 时也删除关联 vector/metadata/auxiliary chunks。重插入以及 IVF/flat 变异均有测试。
- 完整性/故障：读取 KNN chunk 时显式验证 validity、rowids、vectors blob 尺寸；不匹配
  会报错，不会产生看似成功但错位的命中。这是对“索引漂移必须可检测”的直接实现。

## 测试与性能启示

`tests/test-insert-delete.py` 不只断言删除后 SQL 看不见行，还校验 blob 被零化、清空
chunk 可重建、metadata/auxiliary 也被删除。`tests/test-ivf-mutations.py` 再检查 ANN
结果绝不返回已删 rowid，覆盖 delete/reinsert-as-update。`benchmarks/exhaustive-memory/bench.py`
分别计时 build 与逐 query latency，并断言 KNN 返回恰好 `k` 个结果；它是 profile 的
起点，不能单独代表产品级 recall 或真实语义质量。

## 对 harness-mem：adopt / adapt / reject

- **Adopt（0.9.8）**：每种批量重建的 derived index 维护 immutable generation manifest：canonical
  source generation、active ID count、稳定 ID hash、embedding model/dimension、build status
  与创建时间。Doctor 可只读比对 manifest 与 canonical store。
- **Adapt（0.9.8）**：embedding、vec0 与 trigram rebuild 写入 staging generation，完成 count/ID/dimension/readability
  验证后才原子切换 active manifest；删除/supersede 后必须在 FTS、vec0、trigram、relation
  postings 上无幽灵 ID。
- **Reject**：产品代码依赖 `_chunks`/`_rowids` 等私有 shadow schema，或把 C 级 chunk
  管理复制到 Python。harness-mem 应保有 engine-independent canonical-ID integrity contract。

验收建议：随机 100 轮 insert/update/supersede/delete/rebuild 后，canonical active-ID 集合
与每个派生索引完全一致；故意改变 vec dimension、ID hash 或 row count 必须使 Doctor
fail-closed。对 rebuild 的 data-write 前、publish 前、publish 后 cleanup 前注入失败，重启
后只允许读取上一完整 generation。

## 证据表

| 结论 | 本地绝对路径与行号 | 可复核点 |
|---|---|---|
| shadow-table 结构及 KNN plan 编码 | `F:\AIInfra\upstreams\harness-mem\sqlite-vec\ARCHITECTURE.md:13-117` | chunks/rowids/vector/metadata/auxiliary 与 `idxStr` |
| chunks 与 rowid shadow DDL | `F:\AIInfra\upstreams\harness-mem\sqlite-vec\sqlite-vec.c:3409-3436` | `VEC0_SHADOW_CHUNKS_*`、`VEC0_SHADOW_ROWIDS_*` |
| SQLite 查询规划入口 | `F:\AIInfra\upstreams\harness-mem\sqlite-vec\sqlite-vec.c:6012` | `vec0BestIndex` |
| KNN chunk 扫描/过滤入口 | `F:\AIInfra\upstreams\harness-mem\sqlite-vec\sqlite-vec.c:7238,8092` | `vec0Filter_knn_chunks_iter` |
| query-time blob 防错校验 | `F:\AIInfra\upstreams\harness-mem\sqlite-vec\sqlite-vec.c:7379-7421` | validity、rowids、vectors 尺寸不匹配错误 |
| 删除清理物理表示 | `F:\AIInfra\upstreams\harness-mem\sqlite-vec\tests\test-insert-delete.py:73,156,174,197,246-276` | validity、rowid/vector blob、chunk、metadata/auxiliary 测试 |
| IVF 删除与再插入 | `F:\AIInfra\upstreams\harness-mem\sqlite-vec\tests\test-ivf-mutations.py:100,120,477,500` | KNN 无已删行、flat map、reinsert update |
| build/query 性能分开记录 | `F:\AIInfra\upstreams\harness-mem\sqlite-vec\benchmarks\exhaustive-memory\bench.py:12-16,121-164,381-450` | `BenchResult`、build time、query times、`len(result) == k` |
