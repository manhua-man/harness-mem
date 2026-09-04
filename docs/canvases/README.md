# Canvas 图解

Cursor Canvas 交互面板源码。当前架构与检查结果以本目录的 v1 架构图和 convergence 图为准；其余文件是已标明版本的历史快照。上游参考项目的当前版本与采用结论见 [`reference-projects-latest.md`](../reference-projects-latest.md)。

| 文件 | 用途 |
|------|------|
| `harness-mem-readiness-v1.canvas.tsx` | **当前源码**：0.9.27 五模块边界、双执行入口、SQLite truth 与 Scope Ledger |
| `harness-mem-convergence.canvas.tsx` | **当前**：产品边界、实际结果检查、reference-projects 形态对比与 adopt/adapt/reject |
| `harness-mem-readiness-0-9-10.canvas.tsx` | 历史快照：0.9.10 仓库成熟度与当时本机运营状态 |
| `harness-mem-how-it-works-0-9-10.canvas.tsx` | 历史快照：0.9.10 七宿主、7 Daily、27 MCP tools 与 distill/Dream 主链 |
| `harness-mem-reference-comparison.canvas.tsx` | 历史快照：v5.6 十维参考对比 |

已删除或合并进 `harness-mem-convergence.canvas.tsx`：`convergence-before-after`、`completion-0-8x`、`reference-comparison-0-8x`、无版本号的旧 `how-it-works` 与 `completion`（及 IDE 侧 `completion-jul-2026`）。

规范文档：`docs/maturity-model.md`

## 怎么打开

在 Cursor 中打开 `.canvas.tsx` 可渲染为侧边交互面板。

IDE 托管目录（工作区为 harness-mem 时）通常在：

`~/.cursor/projects/f-AIInfra-harness-mem/canvases/`

本目录是 **harness-mem 仓库内真本**，便于与文档一起版本管理。若侧边未自动关联，从本目录或 IDE 托管目录打开文件即可。
