---
name: "HM: Prune KB"
description: 备份并清理 knowledge-base 中 stale/superseded 条目
category: Memory
tags: [harness-mem, prune-kb, knowledge-base]
---

清理 `knowledge-base.md` 中被审查为 `stale` 或 `superseded` 的条目。用户入口是 `/hm:prune-kb`；底层实现会先自动备份。

**Input**: `/hm:prune-kb --statuses stale,superseded`

**Core UX**

- 先备份，再清理。
- 输出必须显示备份路径和删除条目数。
- 如果用户说“只看看”，运行 dry-run。

**Steps**

1. 解析 `--statuses`，默认 `stale,superseded`。
2. 如果用户要求预览，调用：
   ```powershell
   python tools/session-distill/bin/session-distill.py prune-kb --statuses <statuses> --dry-run
   ```
3. 否则调用：
   ```powershell
   python tools/session-distill/bin/session-distill.py prune-kb --statuses <statuses>
   ```
4. 汇报：
   - 候选条目数量
   - 实际删除数量
   - 自动备份路径
   - 是否建议再跑 `/hm:review-kb`

**Notes**

- 这是 `/hm:*` 知识库维护入口，不是核心记忆消费路径。
- 不要静默删除；即使用户要求清理，也要在最终摘要里列清楚结果。
