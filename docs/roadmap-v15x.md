# Roadmap: harness-mem v1.5.x

> 状态：v1.5.0 已收尾，本文件聚焦 v1.5.1 - v1.5.3 的实质工作。
>
> 本轮重写背景：上一版 roadmap 中的若干"P0 任务"已在 v1.4 / v1.5.0 周期内完成，重写时按源码现状重新核对 scope。

---

## 已完成（无需再列入路线图）

源码核对后，以下原计划项目已落地：

- MCP 工具补齐 `reject_rule`（`harness_mem/mcp/server.py: tool_reject_rule`，CLI / MCP / REST 三端对称）
- 跨项目搜索 `scope="all"`（CLI / MCP / REST 入口齐全；`read_api.search_memory_and_observations` 内分支处理）
- `cli.py` 主体瘦身：从 1200+ 行降至 331 行；`commands/` 目录已承接 ingest / wake / status / profile / doctor / search / purge / distill / import_bridge / onboarding 等子命令

---

## v1.5.1：拆分收尾与读路径加固

**目标**：还掉 v1.4 周期遗留的拆分债，加上一条最小可用的自动喂养路径。

| 优先级 | 任务 | 验收 |
|--------|------|------|
| P0 | 把 `cli_commands.py` 剩余 6 个命令（correct / confirm_rule / reject_rule / list_candidates / confirmed_rules / handoff）迁入 `commands/`，并按"IO 与 UI 输出分离"重构 | `cli_commands.py` 删除；新模块各 < 200 行；`pytest` 全绿 |
| P0 | 补齐 `storage/` 单元测试：`local_structured_store` / `local_verbatim_store` / `sqlite_index` 的边界条件（空查询、FTS 特殊字符、并发写入） | 三个文件覆盖率 ≥ 80% |
| P1 | `wake-up` 内置一次轻量 ingest（仅扫描自上次 cursor 以来的新增 session，预算 500 ms，超时即跳过并打日志） | 新会话写入后 `wake-up` 不需手动 `ingest` 即可看到；超时行为有测试 |
| P2 | `wake-up` 输出对截断内容标注 `[...truncated]`，避免 LLM 把截断当完整事实 | 截断标记单测 |

**不列入此版本**：
- "原子性加固"。`storage/sqlite_index.py` 的 FTS 通过同事务 trigger 维护；`HybridSearchLayer` 不持久化向量索引（查询时即算）。两层都不存在脑裂场景，不写空头任务。
- MCP `reject_rule`、scope=all：已完成。

---

## v1.5.2：检索质量调优与跨项目结果元数据

**目标**：把已上线的跨项目搜索补齐元数据，把 R@5 从 0.94 推到 ≥ 0.96。

| 优先级 | 任务 | 验收 |
|--------|------|------|
| P0 | LongMemEval 复跑当前基线，确认 0.9418 复现性，记录每个 question type 的瓶颈（参考 `benchmarks/results/results_harness_hybrid_real_allvec_adaptive_top5_20260510_r2.json`） | 一份 `docs/benchmark/v151-baseline.md`，列出 ≥ 3 个 recall < 1.0 的 case 与定性原因 |
| P0 | Hybrid 权重调优 + 候选池放大实验（FTS 0.4 / Vector 0.6 → 网格搜索；候选池 10× → 20× / 30×） | R@5 ≥ 0.96，p95 latency 不超过当前 baseline 的 1.5× |
| P1 | 跨项目搜索结果带 `project_name` + `tech_stack` 字段（schema 已有 ProjectProfile，read_api 拼接即可） | MCP / REST 返回结构含元数据；适配器消费方有契约测试 |
| P2 | 截断标记与 token 预算计算的口径统一（当前 `formatters.py` 与 `commands/status.py` 的预算估算各算各的） | 一个共享函数；status / profile / doctor / wake 输出口径一致 |

---

## v1.5.3：发布与归档增量化

**目标**：让外部安装与历史会话归档不再卡手。

| 优先级 | 任务 | 验收 |
|--------|------|------|
| P1 | `CodexArchiveAdapter` 增量扫描：按 mtime + 文件大小做 cursor，避免每次全量扫 | 二次运行 < 1s（≤ 1000 文件），结果与全量一致 |
| P1 | PyPI 发布 CI：tag 触发 build + publish，含 wheel + sdist | `pip install harness-mem` 可装，README 安装段可跑通 |
| P2 | `harness-mem doctor` 增加 "下一步建议" 的 error code 索引（每条 error 对应一条修复命令） | doctor 输出含 `code: HM-xxx`，文档列表对照表 |

---

## 关于跳过的若干提案

为了避免下一版又出现"看起来很大但其实已做完"的条目，这里把上一版 roadmap-v15x 里被砍掉的提案也写明，便于后续评审对照：

| 砍掉的提案 | 原因 |
|------------|------|
| "[P0] Blob-索引原子性加固" | FTS 同事务维护，向量层无持久索引，无脑裂场景 |
| "知识卡片 (Knowledge Cards) 元数据封装" | 实质是给跨项目结果加 project_name 字段，已收入 v1.5.2 P1，不另起花名 |
| "Tier 1 Surgical Errors" | 实质是 doctor 错误码表，已收入 v1.5.3 P2，不另起花名 |
| "隐身基石 / Invisible Foundation" | 实质是 wake-up 内置 ingest，已收入 v1.5.1 P1，不另起花名 |
