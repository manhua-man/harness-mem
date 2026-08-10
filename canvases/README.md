# Canvas 图解

Cursor Canvas 交互面板源码。入门与历史快照见下表；**当前成熟度评估** 以 Readiness Ladder v1 为准。上游参考项目的当前版本与采用结论见 [`docs/reference-projects-latest.md`](../docs/reference-projects-latest.md)，下列 comparison canvas 不作为版本真值。

| 文件 | 用途 |
|------|------|
| `harness-mem-readiness-v1.canvas.tsx` | **当前**：0.9.11 六轨 Readiness + Scope Ledger，不用综合分掩盖 live drift/backlog |
| `harness-mem-readiness-0-9-10.canvas.tsx` | 历史快照：0.9.10 仓库成熟度与当时本机运营状态 |
| `harness-mem-how-it-works-0-9-10.canvas.tsx` | 历史快照：0.9.10 七宿主、7 Daily、27 MCP tools 与 distill/Dream 主链 |
| `harness-mem-how-it-works.canvas.tsx` | 历史快照：早期入门流程与旧内部产品面 |
| `harness-mem-convergence-before-after.canvas.tsx` | **历史** 外部分享：十维收敛前后对比（不再作 headline 分） |
| `harness-mem-completion-0-8x.canvas.tsx` | 历史快照：五维评估（v0.8.3） |
| `harness-mem-reference-comparison-0-8x.canvas.tsx` | 历史快照：十维参考对比（v0.8.3） |
| `harness-mem-completion.canvas.tsx` | 历史快照：v5.0 证据链时代完成度 |
| `harness-mem-reference-comparison.canvas.tsx` | 历史快照：v5.6 十维参考对比 |

规范文档：`docs/maturity-model.md`

## 怎么打开

在 Cursor 中打开 `.canvas.tsx` 可渲染为侧边交互面板。

IDE 托管目录（工作区为 harness-mem 时）通常在：

`~/.cursor/projects/f-AIInfra-harness-mem/canvases/`

本目录是 **harness-mem 仓库内真本**，便于与文档一起版本管理。若侧边未自动关联，从本目录或 IDE 托管目录打开文件即可。
