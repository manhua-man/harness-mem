---
name: "HM: Verify Entry"
description: 命中式复查 knowledge-base 条目并输出 grill-style 问题
category: Memory
tags: [harness-mem, verify-entry, knowledge-base, review]
---

按 session id 或关键词命中 `knowledge-base.md` 条目，并给出 grill-style 复查问题。用户入口是 `/hm:verify-entry`。

**Input**: `/hm:verify-entry <session-id|keyword>`

**Core UX**

- 这是定向复查，不是全库扫描。
- 输出命中的条目、来源、当前审查状态和复查问题。
- 不自动删除、不自动改 truth。

**Steps**

1. 解析查询词。
2. 调用实现层：
   ```powershell
   python tools/session-distill/bin/session-distill.py verify-entry <session-id-or-keyword>
   ```
3. 对每条命中项给用户看：
   - line number
   - status
   - source session id
   - text
   - grill-style 复查问题
4. 如果复查显示条目不稳，建议后续跑 `/hm:review-kb` 或 `/hm:prune-kb`，但不要替用户静默删除。

**Notes**

- `verify-entry` 是人工/代理协作复查入口。
- 若无命中，说明没有对应 knowledge 条目，不要把无命中包装成“已经稳定”。
