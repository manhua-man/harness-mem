# docs/

`harness-mem` 的产品文档入口。

当前发版状态、已完成切片和未做边界以 [`roadmap-status.md`](./roadmap-status.md)（**公开状态页**）与
`CHANGELOG.md` 为准。各版本 `roadmap-v*.md` 保留切片设计与历史决策，不单独充当当前实现真值。

## 面向用户

| 文件 | 用途 |
|---|---|
| [`../README.md`](../README.md) | 安装、Golden Path、`/hm:*` 工作流 |
| [`../plugins/harness-mem/README.md`](../plugins/harness-mem/README.md) | Claude Code 插件与 slash 安装 |
| `best-practices.md` | 日常使用建议 |
| `error-codes.md` | `doctor` 的 `HM-xxx` 错误码与修复提示 |
| `roadmap-status.md` | 当前版本、已交付能力、non-goals、已发布的 v3.1-v3.3 与规划中的 v3.4 |
| `testing.md` | 维护者测试分层：日常 focused / fast gate / full release gate |

| 目录 | 内容 |
|---|---|
| `benchmark/` | 检索评测说明与基线报告（偏技术读者） |

## 维护者与发版审计（非大众入口）

以下材料含 scenario 编号、客户端联调记录或实现细节，**不要**当作用户上手文档：

| 文件 / 目录 | 用途 |
|---|---|
| `v2-user-test-packet.md` | v2 跨客户端 release 测试包（maintainer / evidence；**不进**公开 `git archive`，见 [`releasing.md`](./releasing.md)） |
| `roadmap-v29.md` 等 `roadmap-v*.md` | 分版本交付记录与验收口径 |
| `roadmap/` | 历史 roadmap proposal / design drafts（非当前版本承诺） |
| `cli/`、`cli-design-expert.md` | CLI / 维护面设计参考 |
| `reference-projects.md` | 外部 memory 项目参考；本地 upstream 镜像仅维护者自用 |
| `retrospective-v13-v14.md` | 架构演进评审记录 |

LongMemEval / embedding 相关 benchmark 文档默认以 `all-MiniLM-L6-v2` 为基线锚点，除非某份 shootout 明确写了其它模型。

## 版本 roadmap 索引

| 文件 | 用途 |
|---|---|
| `roadmap-v15x.md` | v1.5.x 分切片交付 |
| `roadmap-v16x.md` | v1.6.x：vectors、typing、bucket budget |
| `roadmap-v17x.md` | v1.7.x：temporal、supersede、verbatim search |
| `roadmap-v22x.md` | v2.2.x：IDE 入口闭环 |
| `roadmap-v23.md` | v2.3：Signals / Replay |
| `roadmap-v24.md` | v2.4：host-triggered reflection |
| `roadmap-v25.md` | v2.5：context assembly、wake renderer |
| `roadmap-v26.md` | v2.6：wiki bridge、contradiction 候选 |
| `roadmap-v27.md` | v2.7：cross-project skills |
| `roadmap-v28.md` | v2.8：session-distill maintenance |
| `roadmap-v29.md` | v2.9：PRD sync + maintenance/truth-sync release train |
| `roadmap-v31.md` | v3.1：Auto Dream Memory Maintenance |
| `roadmap-v32.md` | v3.2：Generated Knowledge Compiler + Basic Freshness |
| `roadmap-v33.md` | v3.3：Temporal Query and Supersede Explainability |
| `roadmap-v34.md` | v3.4 规划：Runtime Health, Cost Discipline, and Regression Gates |
| `roadmap-vision-v16-v18.md` | v1.6–v1.8 历史远景（非当前承诺） |

OpenSpec：

- `openspec/specs/`：当前主 spec 真值
- `openspec/changes/`：仍在进行中的 active changes
- `openspec/changes/archive/`：已完成 change 的归档记录

工作流 skill 资产在 `tools/`；插件在 `plugins/harness-mem/`。
