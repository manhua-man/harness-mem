# Output Layout

> Synced from the repo-local session-distill shared template.
> Edit `scripts/ai/session-distill/templates/output-layout.template.md` and rerun `python scripts/ai/session-distill/sync_references.py` from the repo root.

Claude `session-distill` 的默认工作区：

`~/.claude/session-distill`

## 文件布局

- `manifest.json`
  - 已发现 session 及其状态的唯一真值源
- `knowledge-base.md`
  - 跨会话稳定知识层
- `packets/<session-id>.md`
  - 从 Claude `.jsonl` 生成的 review packet
- `distilled/sessions/<session-id>.md`
  - 读完 packet 后写出的 session note
- `memory-drafts/<session-id>.json`
  - 由 `packet-memory-export` 从 packet 导出的结构化 memory draft 队列

## 默认链路

- `raw session / hook 归档 -> packet -> standalone distill（session note / knowledge-base / repo rules）`
- `packet -> packet-memory-export -> memory-drafts -> 人工审阅 / sync-list -> claude-mem` 是增强链路，不是 core parser 的强依赖。
- 也就是说：先用 packet 保住证据面，再决定是否继续导出结构化记忆候选。

## 状态含义

- `new`
  - 已索引，尚未生成 packet
- `bundled`
  - packet 已生成，等待提炼
- `distilled`
  - session note 已写、稳定知识已归档、是否升项目规则也已完成判断
- `skipped`
  - 主动跳过，不参与当前队列

## 推荐循环

1. 运行 `session-distill run --next 1`
2. 只读一个新 packet
3. 更新 `distilled/sessions/<session-id>.md`
4. 把稳定知识归并进 `knowledge-base.md`
5. 判断是否要继续落到 repo 规则或模块文档 / 测试
6. 标记为 `distilled` 或 `skipped`

## Enhanced Path

1. 如果你只做 standalone distill，packet 后面直接接 session note / knowledge-base。
2. 如果你要导出结构化记忆候选，运行 `packet-memory-export export --session <session-id>`。
3. 只有 `ready-candidate` 才表示可进入人工同步审阅；`needs-raw-review` / `needs-conflict-review` 仍需补证。
