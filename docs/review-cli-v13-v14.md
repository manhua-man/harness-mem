# CLI 专家评审 — v1.3/v1.4

评审日期：2026-04-25
基于 `harness-mem v1.2.0` 代码和实际 CLI 输出。

---

## 每条准则逐一评估

### 1. 默认优先 — 做得不错，但有两个缝隙

**好的**：
- `_resolve_project_name()` 三层回退（`-p` -> `HARNESS_MEM_PROJECT` env -> `active_project.txt`），然后在 tty 下交互式 fallback。这是对的设计。
- `quickstart` 自动用 `cwd.name` 作为默认 project name，用户不需要临时想一个。
- `ingest` 默认 `claude-code` 客户端、默认 `-n 10`，第一次用不烧脑。

**缝隙**：
- `timeline` 默认 `limit_arg = 50`（见第 480 行），这是**硬编码在分发逻辑里的**，没有暴露在 argparse 的 `default=` 中。用户跑 `timeline --help` 看不到默认值。
- `search` 需要显式 query 参数，但 `-q/--query` 和 `query_arg` 并列。用户如果只输 `harness-mem search` 看到的是 `error: the following arguments are required` 而非提示"请输入搜索关键词"，这体验不够友好。

### 2. 一步一引导 — 基本达标，但 quickstart 的"引导"不够硬

**好的**：
- `quickstart` 做完后打出了 `Suggested next step`，并列出了 `harness-mem doctor` 作为"Also useful"。
- `doctor` 输出三块：状态诊断 + 最近 sessions + Suggested next step。

**问题**：
- `quickstart` 结束时说 "Suggested next step" 和 "Also useful"，但没有用**视觉区分**。输出尾部有一段 `print()` + 两行命令，对命令行疲劳用户来说容易扫过。建议用分隔线或 `==>` 前缀。
- `doctor` 的 "Suggested next step" 逻辑和 `quickstart` 共享 `_suggested_next_step()`，这是好的。但 `doctor` 的状态信息远远多于"下一步"，用户可能需要滚动才能看到那句唯一重要的建议。违反了"输出回答三个问题"中的"我下一步最该敲哪条命令"。

### 3. 渐进披露 — 较好的实践，但 help 信息分层不够

**好的**：
- 短命令（`ds`, `wake`, `tl`, `st`, `qs`）都存在且合理。
- `quickstart` 只有 `-c` 和 `-n` 两个选项，不吓人。
- `ingest` 只暴露 `-p` 和 `-n`，简单明了。

**问题**：
- `correct` 的 `--help` 列出了 `-s`, `-p`, `-r`, `-t` 四个参数，但它**默认是交互式**的。用户看到 --help 以为是脚本模式，实际是交互式，这个认知落差应该解决。help 文本里应该标注 "（交互式：参数可省略，终端中逐个提示）"。
- `handoff` 同理：`--help` 列了 6 个参数，但运行时会进入交互模式。help 没有提示。
- `profile --edit` 是否进入交互式 edit，在 `profile --help` 里完全没有体现。用户需要知道 `--edit` 会触发什么，应该在子命令 description 或 help 中说明。

### 4. 状态感知 — 核心正确，但在"说什么"上有改进空间

**好的**：
- `_suggested_next_step()` 的决策树很清晰：0 observations -> ingest / 有 obs 无 structured -> distill / 有 structured -> wake。
- 在 `doctor` 和 `quickstart` 的尾部都正确调用了这个决策函数。

**问题**：
- 当 observations 为 0 但没有任何 sessions 时（即用户新装），fallback 是 `harness-mem ingest claude-code -p {project} -n 5`。但新用户更该跑的是 `harness-mem quickstart` 而非 `ingest`。建议将这个 case 的 next step 指向 quickstart。
- `doctor` 对 `L3/L4+` 的 compact 建议写得很好（第 764-766 行），但 `status` 和 `profile` 命令**没有**给出这些建议。用户跑了 `status` 或 `profile` 看到了大量 token 预估但不知道下一步该做什么。

### 5. 输出回答三个问题 — 差距最大

**现状**：
- `doctor` 勉强回答三个问题（主动态、阶段、下一步），但信息密度太高，三个答案散布在 20+ 行输出中。
- `quickstart` 回答了"我发现了什么"（session count、profile），也给了下一步，但没有明确说"现在我处在 X 阶段"。
- `status` 完全没有"下一步"。
- `wake` 输出了"当前状态"但没有"下一步"。

**建议的 v1.3 修复**：
所有会给出建议的命令，在尾部统一追加三行标准化输出：
```
--- 
阶段: ingest / distill / wake  / ready
下一步: harness-mem <command> ...
---
```

---

## Review Checklist 逐条复核

| # | 检查项 | 评估 | 证据 |
|---|--------|------|------|
| 1 | 是否还需要重复输入同一个项目名 | **很好**，`_resolve_project_name` 三层回退 + 自动 set active，用户几乎不需重复输入 | L57-68 |
| 2 | 是否通过默认值或交互式减少参数长度 | **较好**，`-p` 默认 active project；`correct` 和 `handoff` 有交互式 fallback | L503-521, L553-572 |
| 3 | 是否自动发现最近 session 并展示 | **合格**，`quickstart`、`doctor` 都会展示最近 session | L663-672, L733-741 |
| 4 | 是否给出明确的"最佳下一步"而非一串命令 | **基本合格**，`doctor` 和 `quickstart` 给单条命令加 reason；但 `status`、`profile`、`wake` 没给 | L698-714, L768-778 vs L787-803 |
| 5 | 是否把 distill 和 wake 的触发时机说清楚 | **部分满足**，`_suggested_next_step()` 内部说清楚了，但终端用户只有看到 doctor 才知道 | L255-289 |

---

## v1.3/v1.4 优先修复项（按优先级排序）

### P0 — 必须修

1. **`timeline --help` 不显示默认 limit = 50**。把 `default=50` 加到 argparse 参数中，而非在分发逻辑里硬编码。
2. **`search` 在无 query 时给出友好提示而非 argparse error**。捕获 `SystemExit` 后输出 `请输入搜索关键词` 并列出最近的 observation 标题作为引导。
3. **`correct` 和 `handoff` 的 --help 中标注交互式行为**。让用户预知参数可省略、终端会逐个提示。

### P1 — 高优先级

4. **所有带状态输出的命令（status、profile、wake）都在尾部追加"标准化三步"**：当前阶段、下一步命令、简短的 reason。
5. **新用户 0 sessions 时，`_suggested_next_step` 指向 `quickstart` 而非 `ingest`**。

### P2 — 建议

6. **`doctor` 输出分区**：先用分割线把"诊断信息"和"建议"视觉分开。当前诊断 + 建议混在一起。v1.4 可以有个漂亮的分隔区。
7. **`quickstart` 的下一步建议用 `==>` 前缀**，让它在视觉上跳出来。
8. **`profile --category bug` 等类 distill 参数应该统一命名风格**。`distill` 用了 `-c/--category`，但 `correct` 用了 `-r/--pattern` 和 `-t/--trigger`，命名一致性还可以更好。

---

## 总结

CLI 当前处于**功能完整但提示薄弱**的状态。数据层、适配器、结构化 memory 管线都够扎实，几个命令的分发逻辑也清晰合理。最需要投入的是"用户不用猜"——在每个输出点补充阶段标识和下一步命令。这些改动量不大（5-8 处输出调整 + 1-2 处 argparse 修复），但对首次使用和日常使用的体验影响显著。

核心投入顺序：**P0 修复 > 标准化三步提示 > doctor/status 输出分区**。
