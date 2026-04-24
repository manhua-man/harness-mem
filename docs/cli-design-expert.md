# CLI Design Expert

`harness-mem` 的 CLI 设计默认遵循这几条：

## 目标

- 让用户先走通最短 happy path，再暴露高级参数
- 少记命令，少重复输入，少在命令之间来回切换
- `quickstart` 和 `doctor` 不只报告状态，还要告诉用户下一步最该执行什么

## 设计准则

1. 默认优先
   - 优先复用 active project、当前位置和最近一次上下文
   - 能自动发现 session，就不要先要求用户手填 `--project`、`--session-id`

2. 一步一引导
   - `quickstart` 负责初始化、发现最近 session、自动尝试 ingest
   - `doctor` 负责解释当前卡在哪个阶段，并给出单一主建议

3. 渐进披露
   - 先给短命令和交互式模式
   - 长参数只留给脚本化和高级用法

4. 状态感知
   - `0 observations`：建议 `ingest`
   - `有 observations，但无 structured memory`：建议 `distill`
   - `已有 structured memory`：建议 `wake`

5. 输出尽量回答三个问题
   - 我现在发现了什么
   - 我处在闭环的哪一阶段
   - 我下一步最应该敲哪条命令

## Review Checklist

- 是否还需要重复输入同一个项目名
- 是否能通过默认值或交互式输入减少参数长度
- 是否自动发现了最近 session，并把它们展示给用户
- 是否给出了一个明确的“最佳下一步”，而不是把一串命令都扔给用户
- 是否把 `distill` 和 `wake` 的触发时机说清楚了
