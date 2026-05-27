---
name: "HM: Review KB"
description: 审查 session-distill knowledge-base 的稳定性状态
category: Memory
tags: [harness-mem, review-kb, knowledge-base]
---

扫描 `knowledge-base.md`，把条目分成 `stable / needs-review / stale / superseded`，并记录本次审查时间和条目数。用户入口是 `/hm:review-kb`。

**Input**: `/hm:review-kb --next 20`

**Core UX**

- 这是知识库巡检入口，不是让用户读整份文件。
- 输出摘要优先：总数、四类状态计数、前 N 条需要看的条目。
- 只读审查，不清理。

**Steps**

1. 解析 `--next`，默认 20。
2. 调用实现层：
   ```powershell
   python tools/session-distill/bin/session-distill.py review-kb --next <n>
   ```
3. 总结：
   - stable 数量
   - needs-review 数量
   - stale 数量
   - superseded 数量
   - 下次建议：是否需要 `/hm:verify-entry` 或 `/hm:prune-kb`

**Notes**

- 不要让用户手敲底层命令；slash agent 自己运行并解释结果。
- `superseded` 自动判定目前保守，结果应作为复查线索，不是静默真值。
