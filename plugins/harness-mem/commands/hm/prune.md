---
name: "HM: Prune"
description: 清理已经没有 raw source 的 distilled/skipped manifest 占位
category: Memory
tags: [harness-mem, prune, maintenance]
---

清理 session-distill manifest 中已经没有 raw source、且状态为 `distilled` 或 `skipped` 的占位记录。用户入口是 `/hm:prune`；CLI 只是 Slash 背后的实现层。

**Input**: `/hm:prune --statuses distilled,skipped --source-missing`

**Core UX**

- 默认清理的是 manifest 占位，不删除新的 raw transcript。
- 用户不需要知道 manifest 文件在哪。
- 输出必须说明清掉了多少、保留了多少。

**Steps**

1. 解析 `--statuses`，默认 `distilled,skipped`。
2. 若用户写了 `--source-missing`，只处理 `source_missing=true` 的记录；默认也建议带上它。
3. 调用实现层并应用清理：
   ```powershell
   python tools/session-distill/bin/session-distill.py prune --statuses <statuses> --source-missing --apply
   ```
4. 汇报：
   - matched candidates
   - removed entries
   - remaining manifest state

**Notes**

- 不把 prune 描述为核心 CLI 价值；它是 `/hm:*` 维护入口。
- 如果用户只想预览，使用 `/hm:prune ... --dry-run` 的自然语言等价请求时，运行底层命令但不要加 `--apply`。
