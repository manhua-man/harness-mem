## Why

v2.2 把用户可见入口闭环锁住了：`/hm:distill`、`/hm:wake`、`/hm:search`、`/hm:review`
通过 IDE 命令 / Skill / 自然语言驱动 Agent，背后用 MCP 走 candidate-first 循环。
现在系统能产出候选、自动审核低风险项、把高风险项交给用户。但是它**不会自我整理**：

- 旧的 pending 候选越积越多，没有信号选谁该回头看。
- confirmed 记忆被 wake 用过几次、search 命中过几次、有没有被 supersede——
  这些信息散落在 `usage_count` / `last_accessed_at` 这种宽泛字段里，
  没有可重放的"事件流"。
- 没有"谁选了这批旧记忆来整理"的可解释 run 记录；任何后续 metabolism
  动作都会变成黑箱。

v2.3.0 是 **Memory Metabolism foundations 的第一刀**：先把"信号 + 重放窗口
+ run 记录"这层结构地基铺好，**不**写任何 merge / supersede / weak-link
suggestion。后续 v2.3.1 / v2.3.2 才能基于这些信号产出可审核的代谢建议。

这一刀的硬约束是 **candidate-before-truth + no daemon + no auto-mutate truth**——
v2.3 共同原则在 `docs/roadmap-v23.md` 已经写明，本切片完全遵守。

## What Changes

- 新增 `MetabolismRun` 候选 schema：每次代谢运行（即使是 preview）都登记
  run id、project、input window 描述、selected signals、output counts、
  耗时和状态，并落到 structured store 与事件日志。
- 新增结构化 retrieval / review signal：把 confirm / reject / wake-surfaced /
  search-hit / skill-result / supersede-outcome 写入一个统一的
  `RetrievalSignal` 流，复用现有 `events.log` NDJSON 但额外索引到 SQLite，
  让 selector 能高效查询。
- 新增 replay window selector：从近期 observation、stale pending candidate、
  historical truth、低成功率 skill、重复 search hit 中按预算选取整理窗口；
  selector **只读**，输出窗口描述并写一条 `MetabolismRun(status="preview")`
  记录，不产候选、不动 truth。
- 新增 MCP `metabolism_preview` 工具：Agent / Skill 可以显式触发一次
  preview run，得到窗口摘要 + 入选理由 + 预算占用，方便 v2.3.1 和后续
  metabolism suggestion 流程消费同一窗口。
- 新增预算护栏：每条 selector 维度都按 count / token / type 上限截断；
  超额时显式标注 `truncated_within_<dimension>`，避免旧 observation
  淹没当前任务。

## Impact

- **不动**任何已 confirmed truth：v2.3.0 是只读、信号化、窗口化。
- **不动**用户可见 wake / distill / search 默认输出：信号写入是后台
  effect，不进入 wake 上下文；preview run 必须显式调用。
- v2.3.1 (Compression and Stale Suggestions) 可以直接消费 `RetrievalSignal`
  和 `MetabolismRun.input_window` 而不需要再造一遍信号采集。
- v2.7 cross-project skill / activation hint 可以使用同一信号流来定义
  "这条 skill 在哪些情境下被用过"。
- 失败模式：selector / preview 失败时不阻断主任务，只写一条
  `MetabolismRun(status="error")`，并把诊断指针指向 `harness-mem doctor`。
