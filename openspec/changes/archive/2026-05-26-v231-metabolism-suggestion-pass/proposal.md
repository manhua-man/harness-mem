## Why

v2.3.0 落地了"信号 + 重放窗口 + run 记录"的地基：每次有用户可见的
`wake` / `search_memory` / `auto_review_candidates` apply / `record_skill_result` /
`confirm_supersede` 调用都会写一条 `RetrievalSignal`，`metabolism_preview` 工具
能基于这些信号选出五维 replay window 并落一条 `MetabolismRun(kind="preview",
status="preview")` 审计记录。

但 v2.3.0 的硬规矩是 **selector 只读 ids、不读正文、不动 truth、不产候选**。
这意味着：

- `metabolism_preview` 看完窗口就结束。没人基于这窗口产生"建议合并这两条 entry"
  / "建议把这条 30 天没人看的 rule 标 stale" / "建议这条 supersede"。
  `MetabolismRun.output_counts` 永远是 `{"suggestions": 0}`。
- 软 token cap 用 per-id 启发式估（observations 每条 400 token、historical
  300 等）。当 metabolism pass 真要把 window 喂给 LLM 时，估算偏差会让大块
  observation 撑爆 context 或反过来浪费 budget。
- 信号只**收集**，不**应用**。30 天没人 wake_surfaced 的 rule 不会自然衰减、
  低 success_rate 的 skill 不会在 wake 输出里降序、反复 search hit 的 entry
  不会被 boost。selector 把它们列出来给人看，但从来不让信号反向影响排序。

v2.3.1 把这三件 deferred 的事做出来：在已有的 `MetabolismRun` /
`RetrievalSignal` / `select_replay_window` 基础上加 **suggestion pass**，
用同一窗口产出可审核的代谢建议候选；同时把 token cap 升级成基于正文的精确
计算，让 wake / search 排序受信号影响（弱化但不删除 truth）。

硬约束沿用 v2.3.0：**candidate-before-truth + no daemon + no auto-mutate truth**。
所有建议仍走 `confirm_*` / `reject_*` / `auto_review_candidates` 这一层，绝不
直接改 truth；信号应用只调整排序权重，不删除任何记录。

## What Changes

### Suggestion 生成

- 新增三种代谢建议候选：
  - `MergeSuggestionCandidate`：基于 search/embedding 相似度，把内容高度
    重复的 memory_entry / confirmed_rule 两两配对，建议合并。`/hm:review`
    / `auto_review_candidates` 复用现有 candidate apply 路径。
  - `StaleTruthSuggestionCandidate`：在 replay window 的 `historical_truths`
    + 长期未被 `wake_surfaced` / `search_hit` 的 truth 中标记 stale，建议把
      `valid_to` 设为 now（即把它"软退役"）。
  - 沿用现有 `SupersedeCandidate`：suggestion pass 自动产 supersede 候选
    （A 和 B 矛盾且 B 更新），不再需要新增 schema。
- 新增 `select_metabolism_pass` 函数：包裹 `select_replay_window`，对窗口里
  的内容做相似度 + recency 分析，产出上述三类候选。**只读窗口里 ids 对应的
  正文**，不再扫全库。
- 新增 MCP `metabolism_run` 工具（独立于 `metabolism_preview`）：执行真实
  metabolism pass，写 `MetabolismRun(kind="metabolism", status="completed")`
  和它产出的 candidates。`metabolism_preview` 保持纯只读。

### Content-based token trim

- `select_replay_window` 选完 ids 后，把每个 dim 的 `selected_ids` 按精确
  token 数计入 estimate。tokenizer 选型（tiktoken vs sentencepiece）
  延到 design.md 锁。
- 软 cap 砍尾算法不变（`_TRIM_ORDER`、维内删 tail），只是估算从 per-id
  常数换成精确数。`soft_token_budget` note 的分母仍是 `budget.max_total_tokens`
  分子换成精确累计。
- 兼容性：`ReplayBudget.max_total_tokens` 的语义从"启发式估算上限"变成
  "精确 token 上限"。下游消费者应该不受影响（v2.3.0 没人真用这数字喂模型）。

### Weak-link signal application

- 在 wake 渲染时，当一条 rule / entry 满足"30 天内 0 次 wake_surfaced
  且 0 次 search_hit"时，输出排序降到 confirmed truth 的最尾部
  （**不**删除、**不**动 valid_to、**不**降 confidence；只改 wake 输出顺序）。
- 在 search_memory 排序里，给最近 7 天有 `repeat_search_hit` 的 target_id
  加一个固定 boost（默认 +0.1，配置化）。
- 在 wake 时把低 success_rate skill 移到"experimental skills"分组（仍展示，
  但用户能立刻看出来"这条 skill 历史上经常失败"）。
- 配置开关：默认全部开启；在 `harness_mem doctor` 里报告每条规则被信号
  影响了多少（透明度）。

## Impact

- **不动**已 confirmed truth。所有 suggestion 都是新候选，走 review 流程。
- **改变** wake / search 默认输出**排序**：v2.3.1 起 wake 会把"长期没人看
  的 rule"放最尾、search 会 boost repeat targets。如果用户依赖确切顺序，
  会感知；如果只看 top-N，几乎无感。design.md 将给出 opt-out 路径。
- **`metabolism_preview` 输出形态保持兼容**：v2.3.1 的 preview 仍只跑
  selector，不跑 suggestion pass。新工具是 `metabolism_run`，明确划分。
- v2.3.0 的 `MetabolismRun(kind="metabolism")` 一直在 schema 里"占位"，
  v2.3.1 第一次写出 `kind="metabolism"` 的记录。`output_counts` 字段从
  `{"suggestions": 0}` 升级为
  `{"merge_suggestions": int, "stale_suggestions": int, "supersede_suggestions": int}`。
- `MetabolismRun.from_dict` 要保持向后兼容：旧的 `{"suggestions": 0}` payload
  仍能正确反序列化；新代码读老记录默认零计数。
- 失败模式同 v2.3.0：suggestion pass / 信号应用失败不阻断主任务，写
  `MetabolismRun(status="error")` + `harness-mem doctor` 指针。
- 测试面：suggestion pass 的相似度门槛 / boost 系数会引入新的 calibration
  测试族（在 v2.3.0 的 `tests/loop_harness/` 之外，单独建 `tests/metabolism/`）。
