## Why

v1.7.0 已经把 truth 分成 current 和 history，但“旧事实被新事实替代”还缺一个清晰的人工审核闭环。没有 supersede 候选层，AI 只能在候选和 truth 之间二选一，要么太弱，要么越权。

## What Changes

- Add a `SupersedeCandidate` review object for proposed truth replacement
- Expose suggest / confirm / reject flows through CLI and MCP
- Confirming a supersede candidate marks the old truth historical and links the replacement truth without deleting the old record
- Surface supersede candidates in the general candidate list alongside rule, entry, and relation candidates

## Impact

- Conflicting truth becomes reviewable instead of being silently overwritten
- History remains auditable because old records are preserved and linked
- The review flow stays human-in-the-loop and does not auto-confirm replacements
