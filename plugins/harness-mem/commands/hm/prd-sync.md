---
name: "HM: PRD Sync"
description: 从 bundled packets 生成 candidate PRD/roadmap sync note
category: Memory
tags: [harness-mem, prd-sync, roadmap, maintenance]
---

扫描 session-distill 的 bundled packets，识别 PRD / roadmap / scope / architecture 一类讨论，并生成候选同步笔记。用户入口是 `/hm:prd-sync`；它是 maintenance / review bridge，不是直接编辑正式 PRD 的命令。

**Input**: `/hm:prd-sync [--apply]`

**Core UX**

- 默认 dry-run：先告诉用户命中了哪些 packet、检测到哪些 topic。
- 只有显式 `--apply` 才写 `prd-distilled/*.md`。
- 输出是 candidate，不是已落地真值；不要把它包装成“已经同步 PRD”。

**Steps**

1. 解析是否带 `--apply`。省略时保持 dry-run。
2. 调用实现层：
   ```powershell
   python tools/session-distill/bin/session-distill.py prd-sync [--apply]
   ```
3. 总结：
   - 命中的 bundled packet 数量和 session id
   - 命中的 topic 关键词
   - 是否写出了 `prd-distilled/*.md` candidate 文件
   - 明确说明它没有直接修改正式 PRD、roadmap、knowledge-base 或 confirmed truth

**Notes**

- 这是 `/hm:*` 维护入口，不要求用户自己敲底层 CLI。
- 只读取 manifest 里 `bundled` 的 packet；不把 `new` / `distilled` / `skipped` 会话当输入。
- `--apply` 只写 candidate markdown，不直接改正式产品文档。
