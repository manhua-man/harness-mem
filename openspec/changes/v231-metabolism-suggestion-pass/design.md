## Design

v2.3.1 把 v2.3.0 的"窗口 + 信号"地基升级成"建议 + 应用"。本文件锁定三块：

1. Suggestion pass 的算法、候选 schema、MCP 工具划分。
2. Content-based token trim 的 tokenizer 选型与降级路径。
3. Weak-link signal application 在 wake / search 排序里的接入点与 opt-out。

### Suggestion pass

#### 候选 schema 决策

| 类型 | 复用既有 | 新增 |
| :--- | :--- | :--- |
| Merge | — | `MergeSuggestionCandidate` |
| Stale truth | — | `StaleTruthSuggestionCandidate` |
| Supersede | `SupersedeCandidate`（v1.7.1） | — |

**为什么不把 merge / stale 也塞进 `SupersedeCandidate`**：supersede 的语义是
"A 被 B 替代，A 标历史"，merge 是"A 和 B 合成 C，二者都标历史"，stale 是
"A 自然过期，无替代"。三种 valid_to 后果不同，apply 时的 SQL 路径也不同。
塞一起会让 `confirm_supersede_candidate` 的逻辑分支爆炸。

#### `MergeSuggestionCandidate`

```python
class MergeSuggestionCandidate(BaseModel):
    id: str
    project_name: str
    target_a_id: str          # 第一条 truth id
    target_a_kind: Literal["memory_entry", "confirmed_rule"]
    target_b_id: str          # 第二条 truth id
    target_b_kind: Literal["memory_entry", "confirmed_rule"]
    proposed_content: str     # LLM 生成的合并后内容（pass 阶段写入）
    similarity_score: float   # 0..1，触发合并的相似度
    evidence_signal_ids: list[str]  # 触发它的 RetrievalSignal ids
    status: Literal["pending", "accepted", "rejected"]
    created_at: datetime
    metabolism_run_id: str    # 反向追溯到产生它的 run
```

apply：confirm 后 `target_a` / `target_b` 都 `valid_to=now`，
`supersedes` / `superseded_by` 链指向新建 `MemoryEntry(content=proposed_content)`。

#### `StaleTruthSuggestionCandidate`

```python
class StaleTruthSuggestionCandidate(BaseModel):
    id: str
    project_name: str
    target_id: str
    target_kind: Literal["memory_entry", "confirmed_rule", "relation_fact"]
    last_surfaced_at: datetime | None  # 来自 RetrievalSignal 聚合
    days_since_last_surface: int
    evidence_signal_ids: list[str]     # 通常是空（沉默正是它的理由）
    status: Literal["pending", "accepted", "rejected"]
    created_at: datetime
    metabolism_run_id: str
```

apply：confirm 后只设 `valid_to=now`，不新建替代。被 stale 的 truth
仍可通过 `include_history=True` 查询。

#### Suggestion 选择算法

输入：`select_replay_window(...)` 返回的 `ReplayWindow`。

```python
async def select_metabolism_pass(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    budget: ReplayBudget,
    similarity_threshold: float = 0.85,
    stale_silence_days: int = 30,
) -> MetabolismPass:
    window = await select_replay_window(backend, project_name=project_name, budget=budget)
    merge = await _propose_merges(backend, window, threshold=similarity_threshold)
    stale = await _propose_stale(backend, window, silence_days=stale_silence_days)
    supersede = await _propose_supersedes(backend, window)
    return MetabolismPass(window=window, merge=merge, stale=stale, supersede=supersede)
```

`_propose_merges`：在 window 的 `repeat_search_hits` + `historical_truths`
范围内做 embedding 相似度对比（复用 `harness_mem.search` 的 vector 层）。
`similarity > 0.85` 配对入选。每对最多一个候选，避免 N×N 噪声。

`_propose_stale`：在 window 的 `historical_truths` ∪ "30 天内未被任何
信号触及的 confirmed truth" 中筛选；后者通过 `query_retrieval_signals`
反查得到。

`_propose_supersedes`：在 window 的 `historical_truths` 中找 A 已被
supersede 但 B 未确认的链路；这部分大概率小，单独走慢路径。

#### MCP 工具划分

- `metabolism_preview`（v2.3.0，**保持只读不变**）：跑 selector，写
  `MetabolismRun(kind="preview", status="preview")`，不产候选。
- `metabolism_run`（v2.3.1 新）：跑 `select_metabolism_pass`，写
  `MetabolismRun(kind="metabolism", status="completed")`，产出三类候选。
  失败时写 `status="error"` 并返回 doctor pointer，与 v2.3.0 一致。

两个工具的 input_schema 完全相同（project_name + budget），便于 Agent
统一调用。区别仅在副作用。

### Content-based token trim

#### Tokenizer 选型

候选：
1. `tiktoken`（OpenAI）— 跨 GPT-4 / GPT-4o 准；约 8MB 安装包；本仓已可选依赖。
2. `transformers.AutoTokenizer`（HuggingFace）— 灵活但安装重；本仓没用。
3. 字符数 / 4 启发式 — 准确度差但零依赖。

**决策**：用 `tiktoken` 作为可选依赖；缺失时降级到字符数 / 4 启发式并在
`MetabolismRun.notes` 里写一条 `tokenizer_fallback: char-heuristic`。
这样既不强求所有部署都装 tiktoken，又能让有需要的环境拿到准确数。

#### 接入点

`select_replay_window` 在选完 ids 后多走一步：

```python
estimate = 0
for dim_name, dim in dimensions.items():
    for selected_id in dim.selected_ids:
        content = await _fetch_content_for(backend, dim_name, selected_id)
        estimate += _count_tokens(content)
```

`_fetch_content_for` 只读 window 里的 ids 对应的内容（不扫全库），且做
batch IO（一个 `list_memory_entries(ids=[...])` 比逐条快）。

砍尾算法 (`_TRIM_ORDER`、维内删 tail) 复用 v2.3.0；唯一的差别是 `estimate`
减量从常数换成实际 token 数。

#### 兼容性 / 降级

- `_DIM_TOKEN_WEIGHT` v2.3.0 启发式仍保留，作为 tiktoken 缺失时的 fallback
  路径之一（fallback 顺序：tiktoken → 字符 / 4 → 常数权重）。
- `ReplayBudget.max_total_tokens` 的语义在 v2.3.1 起明确为"精确 token"。
  设过 v2.3.0 默认值 16000 的调用方无需改代码——v2.3.0 的启发式比真值偏大
  约 1.5×，所以从启发式过到精确等于 budget 实际"扩容"了，更松而非更紧。

### Weak-link signal application

#### Wake 排序

`wake` 渲染 confirmed rules 时，分组从 v2.2 的两组（profile rules / recent rules）
扩到三组：

1. **Recent active**：30 天内有 `wake_surfaced` 或 `search_hit` 的 rule。
2. **Stable / quiet**：30 天内 0 信号，但仍是 confirmed truth。展示在底部，
   带"未被使用"小标。
3. **Experimental skills**（v2.3.1 新）：active skill 但 `success_rate < 0.5`
   或 `usage_count >= 5 且 success_count == 0`。展示但带 ⚠️ 标。

opt-out：`update_project_profile(weak_link_signals=False)` 关掉所有降权
和分组（默认 True）。

#### Search 排序

`search_memory` 在 hybrid score 上加 boost：

```python
final_score = base_score + repeat_boost
repeat_boost = REPEAT_BOOST_BASE if has_recent_repeat_hit(target_id) else 0.0
```

`REPEAT_BOOST_BASE = 0.1` 模块常量，可通过 `update_project_profile` 调。
"recent repeat hit" 定义：过去 7 天内 `target_id` 至少被 `search_hit` 信号命中 2 次。

#### Doctor 透明度

`harness-mem doctor` 输出新增一段：

```
Weak-link signal influence (v2.3.1):
  rules pushed to 'Stable / quiet' group:    12 / 47
  skills marked experimental:                3 / 21
  search results boosted (last 7 days):      8 distinct targets
```

让用户能一眼看到信号正在以什么方式塑形 wake / search。

### Non-goals (v2.3.1)

- 不引入后台 daemon。`metabolism_run` 仍由 Agent 显式触发（一次代谢一次调用）。
- 不引入 cross-project 信号聚合或建议生成。
- 不让信号修改 truth 的 confidence / valid_to / status——那些只有
  `confirm_*` candidate apply 才能动。
- 不把 suggestion 自动 apply。`auto_review_candidates` 接入这三类候选时
  仍按 v2.2 的 risk gate（merge 默认拒绝低相似度、stale 默认 pending
  待人确认、supersede 走原 v1.7.1 风险逻辑）。
- 不替换 `usage_count` / `last_accessed_at`：它们继续被 wake / search 写入，
  weak-link 应用读它们 + RetrievalSignal 双源数据。

### Open questions

- Tiktoken 选 model encoding（`cl100k_base` vs `o200k_base`）？默认 cl100k 比
  o200k 老但稳，o200k 更准确反映新模型。倾向 cl100k 直到 v2.4 确定主消费方。
- Stale silence_days 应该 30 / 60 / 90？默认 30 给得激进，可能产生很多假阳
  stale 候选。建议第一版默认 60，观察 review 拒绝率再调。
- Weak-link 应用是否应该按项目可关？目前设计里 opt-out 走 `project_profile`，
  但是否应该全局 env 开关 `HARNESS_MEM_WEAK_LINK_SIGNALS=0`？看部署反馈再定。
