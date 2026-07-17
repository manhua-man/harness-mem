# Canvas 图解

Cursor Canvas 交互面板源码。入门与历史快照见下表；**当前成熟度评估** 以 Readiness Ladder v1 为准。上游参考项目的当前版本与采用结论见 [`docs/reference-projects-latest.md`](../docs/reference-projects-latest.md)，下列 comparison canvas 不作为版本真值。

| 文件 | 用途 |
|------|------|
| `harness-mem-readiness-v1.canvas.tsx` | **当前** 成熟度：六轨 Readiness + Scope Ledger + Claim boundary（v0.9.0+） |
| `harness-mem-how-it-works.canvas.tsx` | 入门：项目怎么跑、流程图、名词白话表 |
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
