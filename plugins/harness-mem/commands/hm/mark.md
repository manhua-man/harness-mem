---
name: "HM: Mark"
description: 标记 session distill 状态，并在 distilled 前运行审计 guardrail
category: Memory
tags: [harness-mem, mark, distill, audit]
---

把 session 标记为 `distilled` 或其它显式状态。用户入口是 `/hm:mark`；底层脚本只是实现层，不要求用户打开终端。

**Input**: `/hm:mark <session-id> distilled [--keep-raw]`

**Core UX**

- 这是 `/hm:distill` 后的收尾入口，不是普通 CLI 教程。
- `distilled` 不是随手打标签；必须先通过审计。
- 审计失败时，直接告诉用户缺哪块证据或哪条候选还没处理。

**Steps**

1. 解析 `session-id`、目标状态和可选 `--keep-raw`。
2. 调用 repo-local 实现层：
   ```powershell
   python tools/session-distill/bin/session-distill.py mark <session-id> distilled [--keep-raw]
   ```
3. 若返回失败，摘要列出 guardrail 拦截原因：
   - 缺 `distilled/sessions/<session-id>.md`
   - partial packet 没写 raw review
   - `Promotion Decision` 仍是 pending/TODO
   - memory draft 还有 pending
   - 同源 `knowledge-base.md` 条目不稳定
4. 若成功，告诉用户：
   - session 已落 `distilled`
   - raw 是否删除、保留或因非白名单路径未删除
   - manifest 是否保留 `source_missing` / `raw_deleted_at`

**Notes**

- 不要把这包装成让用户手敲 CLI；slash agent 自己调用实现层。
- raw 删除只允许实现层的安全白名单执行；非白名单 raw 保留并说明原因。
