# 五方评审盲区 — 额外建议

> 五份评审（CEO/Eng/Design/DevEx/CLI）覆盖了主流路线，但以下切入点全部未被提及。
> 评审日期：2026-04-25

---

## 1. CI/CD — 43 个测试零 CI

当前 43 个 pytest 全在本地跑，没有 GitHub Actions / 任何 CI 配置。这意味着：
- PR 合入前无人确保测试通过
- `pip install -e .` 的跨平台兼容性从未被验证（Win/Mac/Linux）
- SQLite FTS5 在不同平台的微妙差异无法被捕获

**建议：** 这是**最小的"基建性"投入**——一个 `.github/workflows/test.yml` 文件，3 个 matrix job（ubuntu/macos/windows），成本几乎为零但门禁效果显著。建议放在 v1.3 的 P2 DevEx 基建中。

---

## 2. 增量 ingest — 每次全量扫描的浪费

当前 ingest 每次遍历所有 session 文件并重新处理。没有维护"已 ingest 到哪个 session"的游标。

| 场景 | 当前行为 | 问题 |
|------|---------|------|
| 第一次 ingest -n 10 | 取 10 条，正常 | — |
| 第二天再 ingest -n 10 | 重新处理前 10 条，产生重复 observation | 浪费 + 重复 |
| 有 1000+ session | 每次遍历所有文件 | 随数据量线性退化 |

**建议：** 在 active project 中记录 `last_ingested_at` 或 `last_ingested_session_id`。增量模式只处理新 session。可以放在 v1.4 作为 P2 改进。

---

## 3. Codex adapter — 先天不足

评审里没人认真看过 Codex adapter。实际上它非常薄弱：

```
adapters/codex/adapter.py:
  - list_sessions()    → 读 ~/.codex/sessions/ 目录
  - read_session()     → 读单个 session 文件
  - ingest_latest()    → 简单的 for 循环
```

后端 `list_sessions()` 按 `min_size_kb=1` 过滤，没有：
- session 元数据解析（model、duration、token count）
- session 状态过滤（completed vs crashed）
- 增量 ingest 支持
- 错误恢复（部分损坏的 session 文件导致整个 ingest 中断）

**建议：** v1.3 或 v1.4 中花半天加固 Codex adapter 的错误处理。不需要重写，但要让它能应对真实场景中的 10+ 种异常。

---

## 4. Shell Tab Completion — 零成本高回报

argparse 原生支持 `argparse.REMAINDER` 和 shell completion。目前完全没有启用。

```bash
# 当前
harness-mem <TAB> → （无反应）

# 应做到
harness-mem <TAB> → ingest  distill  wake  search  timeline  show  status  ...
harness-mem i<TAB> → ingest
harness-mem ingest -<TAB> → --project  --limit  --help
```

**建议：** 将 argparse 的 `add_completer` 机制接上。有三种路径：
- 轻量：argparse 内置 `argparse.REMAINDER` + `argparse.ONE_OR_MORE`
- 标准：`argcomplete`（pip 包），对现有 argparse 零侵入
- 无依赖：基于现有 parser 的 `_actions` 手写 bash/zsh completion 函数

推荐 argcomplete。这是**小型改动、日常高频获益**。v1.3 P2。

---

## 5. Dogfooding = 0 — 自己不用自己的产品

```bash
ls ~/.harness-mem/data/  # 不存在或为空
```

harness-mem 的开发过程中，从来没有用 harness-mem 来记录自己的开发记忆。这是最直接的 dogfooding 缺口：
- 自己在 develop 过程中有没有踩过关于 `sqlite_index.py` 的 bug？——没有记录
- 关于 `cli.py` 拆分的最佳决策有没有被 capture？——没有
- 开发者是否愿意在日常工作中使用自己的 CLI 工具？——不知道

**建议：** 这不是一个功能，而是一个实践。在 v1.3 开发周期内要求：每个合入的 PR 必须附带一条通过 `harness-mem correct` 记录的学习。这会暴露所有真实使用场景下的体验断裂点。

---

## 6. 性能基线 — 不知道上限在哪

43 个测试全是功能测试，没有性能基准：
- ingest 500 个 session 需要多久？
- SQLite FTS5 在 10 万条 observation 上 search 延迟多少？
- wake-up 在 L4+ 时生成时间？
- 向量模型首次加载延迟（~100MB）

**建议：** 在 `tests/` 下加一个 `bench_basic.py`，用 `pytest-benchmark` 或简单的 `time.time()` 检测关键路径的延迟基线。持续集成中跑。v1.4 P2。

---

## 7. Memory Export / Import

当前所有数据在 `~/.harness-mem/data/`，换机器就是搬家问题。

**建议：** 这不是 v1.3 或 v1.4 必须做的。但值得提供一个极简方案：`tar czf` 整个 data 目录 + 一个 `--restore` 命令。最多半天工作量。标记为 v1.5 候选。

---

## 8. Session Tagging

当前 session 检索只能靠全文搜索。用户不能打标签（如 "sprint-24", "auth-refactor"）。

**建议：** 在 profile 或 observation 上新增 `tags` 字段。`search --tag auth-refactor` 直接过滤。v1.4 或 v1.5。

---

## 9. MCP 被动推送

目前 MCP 工具全是拉模式：search/timeline/create_rule 都需要 Claude Code 主动调用。harness-mem 作为 memory runtime，本可以在 distill 完成后主动通知 Claude Code。

**建议：** 这需要 MCP 协议侧支持（notification 机制）。当前 MCP spec 有限，但可以在 Claude Code 端轮询 "有新 distill 结果吗"。这不是 v1.3/v1.4 必须做的，但值得在 V2 中考虑。

---

## 10. 跨项目关联检索

当前 search scope 是单个 project。但用户可能在多个项目间切换，想搜"我记得在哪里处理过 JWT 相关的问题"——跨项目检索。

**建议：** 搜所有项目的 observation。argparse 加一个 `--all-projects` flag。这在 v1.4 是小型改动（engine 层已在 `search()` 中接受 project_name 参数）。

---

## 优先级速览

| # | 建议 | 影响 | 工作量 | 建议版本 |
|---|------|------|--------|---------|
| 1 | CI/CD GitHub Actions | 门禁保障 | 小（半天） | v1.3 P2 |
| 2 | 增量 ingest | 性能 + 去重 | 中（1-2天） | v1.4 P2 |
| 3 | Codex adapter 加固 | 稳定性 | 小（半天） | v1.3 P2 |
| 4 | Shell tab completion | 体验 | 小（半天） | v1.3 P2 |
| 5 | Dogfooding 实践 | 质量 | 0 代码 | v1.3 立即 |
| 6 | 性能基线测试 | 可观测性 | 小（半天） | v1.4 P2 |
| 7 | Export/Import | 可迁移性 | 小（半天） | v1.5 |
| 8 | Session tagging | 检索增强 | 中（1天） | v1.4 P3 |
| 9 | MCP 被动推送 | 架构 | 大 | V2 |
| 10 | 跨项目检索 | 功能 | 小（几小时） | v1.4 P2 |
