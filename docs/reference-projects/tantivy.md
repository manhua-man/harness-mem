# Tantivy

- 定位：本地索引发布、文件完整性与故障恢复的参考实现；不是替换 harness-mem SQLite
  存储的理由。
- Upstream：<https://github.com/quickwit-oss/tantivy>
- 本地镜像：`F:\AIInfra\upstreams\harness-mem\tantivy`
- 已核验 HEAD：`667132fa7ab4a30e0c1870d791f23902ebfc6152`（2026-08-01）。

## 架构与数据流

Tantivy 的 writer 将增删写入一个未发布的 indexing state，`prepare_commit()` 切分当前
批次，`commit()` 发布新的 index metadata/opstamp，reader reload 后看见新 searcher；
`rollback()` 放弃未发布状态。segment 文件由 `ManagedDirectory` 管理：文件在创建前注册，
文件 footer 带 CRC，GC 在 meta/file lock 下依据 live-file 集合删除不可达文件。

这形成清晰的数据流：canonical write batch -> staged segment files -> prepared metadata ->
atomic commit/publication -> reader reload -> 后续 GC。关键价值在于“发布点是单一、可检查的
generation”，而不是 Lucene-style segment 格式本身。

## 索引、更新、删除与故障语义

- 索引模型：immutable-ish segment 加 metadata generation/opstamp；读者只消费已发布
  metadata 指向的 segment 集合。
- 更新/删除：delete operation 被排入 writer，直到 commit 才对 reader 可见；rollback
  回到最后成功 commit。其性质测试组合 add/delete/query-delete/commit/merge，验证长序列
  不出现错删或漏删。
- 故障完整性：受管文件先登记，避免“创建后崩溃而 GC 永远不知道”的孤儿；GC 在锁下
  计算 living files，删除失败时文件仍留在 managed list；footer checksum 可识别损坏。
  failpoint tests 验证 metadata 写失败后旧索引仍可读且新文档不可见。

## 测试与性能启示

测试组合了 unit commit/rollback、prepared commit abort、GC delete failure、segment flush/
commit failure 和 proptest mutation sequence。其重点是恢复不变量：失败不能发布半个新
generation、GC 失败不得失去日后重试能力、已删除文档不能在 merge 后复活。性能 benchmark
覆盖 postings、bitset、store、query intersection 等微组件；对 harness-mem 更有用的是将
integrity regressions 与性能 profile 分开，不用微基准冒充端到端检索质量。

## 对 harness-mem：adopt / adapt / reject

- **Adopt（0.9.8）**：为 vec0、embedding 与 trigram 的批量 rebuild 做 staging generation、
  immutable manifest 和 atomic active pointer。成功切换前验证 count、canonical ID hash、
  embedding dimension/model、readability；失败继续服务上一 generation。
- **Adapt（0.9.8）**：FTS 与 relation 保留 SQLite 同事务 trigger 更新；Doctor 以只读 probe 验证 manifest、SQLite rows、vec0 query 与
  checksum/hash；故障注入覆盖 data write 前、manifest publish 前、cleanup 前。repair 只能
  显式 rebuild，不能后台静默重建。
- **Reject**：因这些优点直接引入 Tantivy/Rust 全文搜索或复制 segment 文件格式；也不应
  假设 mmap 环境（特别是 Windows）可立即删除打开文件。复制原子发布纪律即可。

验收建议：四个 rebuild 故障点均在 restart 后保留上一 active generation；随机 100 次
insert/update/supersede/delete/rebuild 保证 canonical 与全部派生索引 ID 集合相同；篡改
manifest hash/dimension/row count 时 Doctor 不得报告 healthy，必须分类为 safe_rebuild 或
snapshot-required。

## 证据表

| 结论 | 本地绝对路径与行号 | 可复核点 |
|---|---|---|
| rollback、prepare、commit、delete API | `F:\AIInfra\upstreams\harness-mem\tantivy\src\indexer\index_writer.rs:564,599-665,680-716` | rollback、prepare cut、commit publish、delete、opstamp |
| commit/rollback 与 prepared abort 测试 | `F:\AIInfra\upstreams\harness-mem\tantivy\src\indexer\index_writer.rs:1029-1058,1212-1237` | 可见性/rollback 与 abort payload |
| 随机 mutation/merge 性质测试 | `F:\AIInfra\upstreams\harness-mem\tantivy\src\indexer\index_writer.rs:2512-2539` | add/delete/commit/merge proptest |
| 受管文件 GC 与锁语义 | `F:\AIInfra\upstreams\harness-mem\tantivy\src\directory\managed_directory.rs:95-209` | live files 在锁下计算，失败删除不丢状态 |
| 创建前注册与 CRC 校验 | `F:\AIInfra\upstreams\harness-mem\tantivy\src\directory\managed_directory.rs:213-243,286-298`; `F:\AIInfra\upstreams\harness-mem\tantivy\src\directory\footer.rs:3` | register-before-write 与 footer checksum |
| GC/commit/flush failpoints | `F:\AIInfra\upstreams\harness-mem\tantivy\tests\failpoints\mod.rs:8-120` | GC delete failure、metadata write、flush、commit failure |
