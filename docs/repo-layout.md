# harness-mem 仓库地图

这份文档只回答一个问题：`harness-mem` 根目录下每个主要目录是干什么的。

如果你刚打开仓库，建议先看这三个位置：

1. `README.md`
2. `harness_mem/`
3. `tests/`

---

## 最重要的目录

| 路径 | 用途 | 是否应长期保留 |
|------|------|----------------|
| `harness_mem/` | 主产品源码，CLI、adapter、storage、API、MCP 都在这里 | 是 |
| `tests/` | 自动化测试，现已按 `cli/api/mcp/storage/integration/benchmark` 分层 | 是 |
| `docs/` | 设计说明、benchmark 记录、评审文档、最佳实践等 | 是 |
| `benchmarks/` | benchmark 相关结果与后续评测产物 | 是 |
| `README.md` | 项目总入口 | 是 |
| `pyproject.toml` | Python 包配置与 CLI 入口 | 是 |

正常情况下，你理解这个仓库时，优先只关注这一层：

- `harness_mem/`
- `tests/`
- `docs/`
- `benchmarks/`
- `README.md`
- `pyproject.toml`

---

## 协作 / 工作流目录

| 路径 | 用途 | 说明 |
|------|------|------|
| `.github/` | CI / GitHub Actions | 仓库标准配置 |
| `.claude/` | Claude Code 命令与 skills | 给 Claude 生态用 |
| `.codex/` | Codex skills | 给 Codex 用 |
| `.cursor/` | Cursor 命令与 skills | 给 Cursor 用 |
| `openspec/` | 变更提案、spec、tasks 等追踪资产 | 工作流资产，不是业务代码 |

这些目录看起来“外围”，但它们是这个仓库的 AI 协作层，不建议随意挪动。

---

## 辅助技能 / 蒸馏工具目录

| 路径 | 用途 | 说明 |
|------|------|------|
| `session-distill/` | 原始 session 整理与 distill 工具资产 | 偏 workflow / skill |
| `mem-distill/` | 已有 memory 的整理技能资产 | 偏 workflow / skill |

它们不是 `harness_mem/` 包的一部分，更像是仓库内附带的配套工具说明。

---

## 本地生成物 / 临时目录

这些通常不应该成为你“理解项目结构”的一部分：

| 路径 | 类型 | 建议 |
|------|------|------|
| `.pytest_cache/` | pytest 缓存 | 忽略 |
| `.mypy_cache/` | mypy 缓存 | 忽略 |
| `.ruff_cache/` | ruff 缓存 | 忽略 |
| `.coverage` | coverage 输出 | 忽略 |
| `.gstack/` | 本地 QA / agent 运行产物 | 忽略 |
| `tmp-review-a/` | 临时 review 数据目录 | 忽略 |

如果这些目录出现在根目录里，不代表项目结构设计如此，只是本地运行后留下的产物。

看到这类目录时，默认先把它们归类为“可删的本地痕迹”，而不是“需要理解的项目模块”。

---

## 建议的阅读顺序

如果你是第一次回到这个仓库，建议按这个顺序看：

1. `README.md`
2. `docs/repo-layout.md`
3. `harness_mem/`
4. `tests/cli/`
5. `docs/best-practices.md`

---

## 一句话判断

- 想看产品代码：进 `harness_mem/`
- 想看行为验证：进 `tests/`
- 想看说明文档：进 `docs/`
- 想看 benchmark：进 `benchmarks/`
- 看到缓存或 `tmp-*`：默认把它当本地产物，不当成仓库主结构
