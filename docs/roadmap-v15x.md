# Roadmap: harness-mem v1.5.x

> 状态：v1.5.1 已完成并通过本地回归；本文件当前保留 v1.5.1 交付记录，并继续作为 v1.5.2 - v1.5.3 的待办路线图。
>
> 本版本经过 CEO / DX / Eng 三层评审重写，每条任务的验收都以源码或基线数字为锚，不写无 baseline 的承诺。
>
> 三个版本的用户视角故事线：
> - **v1.5.1** — 不再需要手动 `harness-mem ingest`，wake 时自动同步新会话
> - **v1.5.2** — 跨项目搜索结果带项目背景；R@5 ≥ 0.95
> - **v1.5.3** — `pip install harness-mem` 即装即用，doctor 给具体错误码与修复路径

---

## 已完成（不再列入 roadmap，留作对照）

源码核对后，以下原计划项目已落地：

- MCP 工具补齐 `reject_rule`（`harness_mem/mcp/server.py: tool_reject_rule`，CLI / MCP / REST 三端对称）
- 跨项目搜索 `scope="all"`（CLI / MCP / REST 入口齐全；`read_api.search_memory_and_observations` 内分支处理）
- `cli.py` 主体瘦身：从 1200+ 行降至 331 行；`commands/` 目录已承接 ingest / wake / status / profile / doctor / search / purge / distill / import_bridge / onboarding 等子命令
- `tests/storage/` 已有四个测试文件、约 26 个用例（不再写"缺乏存储层单测"，而是"覆盖不均"——见 v1.5.1）

---

## v1.5.1：已完成（自动同步与拆分收尾）

**用户故事**：用户写完会话不再需要主动 `ingest`；下一次 wake 自动消化新会话，并在输出里告诉用户"同步了几条、用了多久"。

**前置基线（v1.5.1 启动当日跑一次，写入 `docs/benchmark/v151-baseline.md`）**：
- `pytest --cov=harness_mem.storage` 当前覆盖率（按文件）
- `harness-mem wake` 在 N=10 / 100 / 1000 entries 项目上的 P50 / P95 耗时
- benchmark 脚本扩展为 per-query latency（用于 v1.5.2，越早跑越好）

| 优先级 | 任务 | 验收 |
|--------|------|------|
| P0 | `wake-up` 内置轻量自动 ingest（仅扫描自上次 cursor 以来的新会话、写入 verbatim observations，**不跑 LLM distill**） | 新会话写入后下一次 `wake-up` 自动可见；distill 仍是显式步骤；超时/错误时不阻断 wake |
| P0 | 自动 ingest 的预算与可见性：单次预算 P95 ≤ 300ms（基于 v1.5.1 启动基线 × 1.5）；超时即跳过；输出固定摘要行 `🔄 Auto-synced: N new sessions ingested (Xms)`，零新增时打印 `🔄 Auto-sync: up to date` | 三种行为（同步成功 / 无新增 / 超时跳过）各有单测；摘要行格式与 status / doctor 的 phase 行风格一致 |
| P0 | 自动 ingest 可关：`harness-mem wake --no-auto-ingest` flag 与 `~/.harness-mem/config.toml` 的 `[wake] auto_ingest = true \| false`，CLI flag 优先于 config | flag / config 读取均有单测；关闭后行为与 v1.5.0 完全一致 |
| P1 | `wake-up` 输出对截断内容标注 `[...truncated]`（升级理由：wake 输出本身就是 LLM prompt，截断不标会变成幻觉源，是正确性问题不是体验问题） | 截断单测；status / profile / wake 三处 token 估算口径统一 |
| P1 | 把 `cli_commands.py` 剩余 6 个命令（correct / confirm_rule / reject_rule / list_candidates / confirmed_rules / handoff）迁入 `commands/`，按"IO 与 UI 输出分离"重构 | `cli_commands.py` 删除；新模块各 < 200 行；既有测试全绿 |
| P1 | storage 测试覆盖均衡：`local_verbatim_store.py` 当前仅 1 个用例，目标提至与 `local_structured_store.py` 同档（两者覆盖率差 ≤ 5 个百分点） | 用 v1.5.1 启动基线作为锚定参考，不拍绝对数字 |

### 本次实际落地（2026-05-16）

- `wake-up` auto-sync 已进入主路径，并吸收了 Dream-style 的 per-project runtime 机制：`projects/<slug>/runtime/.ingest-lock` 的 `mtime` 作为最近一次成功 auto-ingest cursor，文件 body 保存 `pid / state / last_session_id / updated_at`；`projects/<slug>/runtime/.ingest-scan-stamp` 作为持久化 scan throttle。
- auto-sync 现在按“**时间门 -> 会话门 -> 锁门**”执行：先挡掉最便宜的无意义 wake，再用候选 session 计数判断是否值得 ingest，最后才尝试持锁。
- 默认门控参数已进入 `wake` 配置语义：`auto_ingest_min_interval_seconds=300`、`auto_ingest_min_new_sessions=1`、`auto_ingest_scan_throttle_seconds=60`、`auto_ingest_lock_ttl_seconds=3600`。
- auto-sync 仍然只写 **verbatim observations**，不跑 LLM distill；成功 / 无新增 / 超时 / 显式关闭 / 时间门 / scan throttle / 锁门这七条路径都已补齐测试。
- `harness-mem wake --no-auto-ingest` 与 `~/.harness-mem/config.toml` 的 `[wake] auto_ingest = false` 已打通。
- `cli_commands.py` 已删除；`correct / confirm / reject / candidates / confirmed-rules / handoff` 已迁入 `commands/`，兼容行为回收到已有命令实现。
- `wake-up` 的截断输出已显式标注 `[...truncated]`，避免下游 LLM 把截断文本误认成完整事实。
- `local_verbatim_store.py` 在 `tests/storage` 覆盖快照中已从 baseline 的 `52%` 提升到 `89%`；同一命令下 storage 总覆盖率为 `80%`。

### 本次重新执行的验收

- `python -m pytest -q` -> `194 passed`
- `python -m ruff check harness_mem` -> pass
- `python -m mypy harness_mem` -> pass
- `python -m pytest tests/integration/test_wake_auto_ingest.py tests/cli/test_learning_loop.py tests/storage/test_local_verbatim_store_deep.py -q` -> `17 passed`
- `python -m pytest --cov=harness_mem.storage --cov-report=term tests/storage -q` -> `local_verbatim_store.py 89%`, storage total `80%`
- `python benchmarks/scripts/v151_latency_baseline.py` -> 已刷新 `docs/benchmark/v151-baseline.md`；当前 synthetic wake P95 为 `24.64ms / 25.57ms / 22.69ms`（N=`10 / 100 / 1000`）

### 本次已吸收的 Dream-style refinement

- `docs/roadmap/dream-mechanism-absorption-v151-v17.md` 中提出的 per-project `.ingest-lock`、`.ingest-scan-stamp`、以及“时间 -> 会话 -> 锁”的三段 gate，现已进入 `wake-up` 主路径。
- 当前 `v1.5.1` 的结论是：既保留了“自动同步可用、不会重复 ingest、可关闭、可测试”的用户体验，也把最值得吸收的 Dream-style gate / throttle / cursor 机制做进了代码。

**不列入此版本**：
- "原子性加固"。`storage/sqlite_index.py` 的 FTS 通过同事务 trigger 维护；`HybridSearchLayer` 不持久化向量索引（查询时即算 embedding）。两层都不存在脑裂场景，不写空头任务。
- MCP `reject_rule`、scope=all、cli.py 瘦身：已完成。
- 完整 daemon / Proactive / KAIROS 风格运行时：不引入。
- AI 自治删除已生效记忆：不引入。

---

## v1.5.2：检索质量诊断驱动调优

**用户故事**：跨项目搜索时返回的不止文本，还告诉 AI 这条记忆来自什么项目、什么技术栈，避免 AI 把 React 项目的规则套到 Vue 项目。整体 R@5 从 0.9418 提到 ≥ 0.95。

**关于 R@5 目标**：上一版本曾考虑 0.96。最终定 **0.95**——从 0.9418 起步是 +0.8 pp，在 500 题上意味着修复约 4 个 case，单一周期可控；剩余空间留给 v1.6 的向量模型升级（all-MiniLM-L6-v2 → 更大模型），不在小模型上压榨边际。

| 优先级 | 任务 | 验收 |
|--------|------|------|
| P0 | 召回失败诊断：把当前 baseline 中 recall < 1.0 的所有 case 跑 ablation（纯 FTS / 纯 Vector / 当前 Hybrid 三组），按失败原因分桶（FTS 漏召 / Vector 漏召 / 融合排序错） | `docs/benchmark/v152-recall-failure-analysis.md`，每桶≥ 1 个代表性 case |
| P0 | 按诊断结果对症下药（**禁止在没分桶前先调权重**）：FTS 漏召 → tokenizer / 同义词扩展；Vector 漏召 → 候选池放大或 query 改写；融合排序错 → RRF 权重 | R@5 ≥ 0.95；P95 query latency 不超过 v1.5.1 baseline × 1.2 |
| P1 | 跨项目搜索结果带 `project_name` + `tech_stack` 字段（schema 已有 ProjectProfile，read_api 拼接） | MCP / REST 返回结构含元数据；契约测试覆盖三端 |
| P2 | token 预算计算口径统一收尾（与 v1.5.1 截断标记一并落） | 单测验证 status / profile / doctor / wake 输出一致 |

**关键前提**：v1.5.1 必须先把 benchmark 扩展为 per-query latency 采集——否则 P0 第二条的"latency 不劣化"无从验证。这是上一版 roadmap 的隐性漏洞，本版强制前置。

---

## v1.5.3：发布与归档增量化

**用户故事**：新用户能 `pip install harness-mem` 直接装上；老用户的 Codex 历史会话归档不再每次全量扫；遇到错误能看到 `code: HM-xxx` 与对应修复命令。

| 优先级 | 任务 | 验收 |
|--------|------|------|
| P1 | `CodexArchiveAdapter` 增量扫描：按 mtime + 文件大小做 cursor，避免每次全量扫 | 二次运行 < 1s（≤ 1000 文件），结果与全量一致 |
| P1 | PyPI 发布 CI：tag 触发 build + publish，含 wheel + sdist | `pip install harness-mem` 可装，README 安装段端到端可跑 |
| P2 | `harness-mem doctor` 增加错误码索引（每条 error 对应一条修复命令） | doctor 输出含 `code: HM-xxx`；`docs/error-codes.md` 列出对照表 |

---

## 上一版 roadmap 中被砍掉的提案

为避免下一轮评审又出现"看似宏大其实已做完"的条目，把砍掉的明确写出来：

| 砍掉的提案 | 砍掉原因 |
|------------|---------|
| "[P0] Blob-索引原子性加固 / 防脑裂" | FTS 同事务 trigger 维护；向量层无持久索引（查询时算）。两层都无脑裂场景。 |
| "知识卡片 / Knowledge Cards" | 实质是给跨项目结果加 project_name + tech_stack 字段，已收入 v1.5.2 P1，不另起花名 |
| "Tier 1 Surgical Errors" | 实质是 doctor 错误码表，已收入 v1.5.3 P2，不另起花名 |
| "隐身基石 / Invisible Foundation" | 实质是 wake-up 内置 ingest，已收入 v1.5.1 P0，不另起花名 |
| R@5 ≥ 0.96 | 改为 0.95，剩余空间留给 v1.6 向量模型升级 |
| "p95 latency 不超过 baseline 1.5×"（不带 baseline 来源） | 当前 benchmark 不采集 latency。改为 v1.5.1 强制前置任务，v1.5.2 才能引用 |
