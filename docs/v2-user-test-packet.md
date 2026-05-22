# harness-mem v2.0 用户测试 Packet

> 给开发者扮演用的脚本。**不是 marketing persona**，是给你在 Codex CLI / Claude Code / Cursor 三个客户端里 stress test v2.0 的具体角色。
>
> 核心要测的事：v2.0 砍掉了 heuristic distill 之后，**任意 LLM agent 通过 MCP 驱动 distill 主链**这条承诺，在三个客户端里是否真的成立。
>
> 预计每个 persona 30-60 分钟。建议三个都跑一遍，写下来在哪里卡住。
>
> 此 packet 由 `.claude/skills/multi-client-field-test/` 生成。下个发版（v2.1 / v3 等）需要新 packet 时调用同一个 skill；本文件本身不是模板。

---

## 共用扮演纪律

不管你扮演哪个 persona，请遵守：

1. **忘掉你是 harness-mem 开发者**。你不知道 `harness_mem/commands/auto_review.py` 长什么样，你只看 README、quickstart 输出和 agent 给你的回复。
2. **只读 persona 角色卡里写的文档**。不去翻 CHANGELOG、`tools/session-distill/SKILL.md`、source code。如果你忍不住想翻 source 才能继续，**那就是一个真问题**——记下来。
3. **遇到卡点先记，再决定要不要绕过**。一卡就翻 source 解决，等于把"它对真用户能不能用"这件事自己作弊回答了。
4. **错误信息照原样抄进反馈表**。不要总结成"distill 报错"，要抄出来。
5. **使用真项目而不是空仓库**。v2.0 distill 依赖真实 session 的语义内容；空仓库下 LLM agent 会幻觉，测出来的不是产品问题是测试设置问题。

---

## Persona A: 林安宁（Claude Code 重度用户）

### 角色卡

- 30 岁，后端工程师，一线 SaaS 公司，独立维护一个 Django + PostgreSQL 项目（约 6 万行）
- 重度 Claude Code 用户，每天 5-7 小时在 agent 里写代码
- 关键痛点：Claude 反复忘掉这个项目用 PostgreSQL **JSONB**（不是 MySQL JSON），每次新 session 都要重新提醒 `JSONField(encoder=DjangoJSONEncoder)`、`GIN index`、`db_index=True` 这些约定。三个月里他重复说过 ≥ 8 次。
- 上 HN 看到 harness-mem 的 "local-first AI memory runtime" 标语，下载来试。
- 之前试过 mem0、letta，嫌 cloud-only 或 setup 太重。

### 你被允许读的文档

- `README.md`（只读 v2.0 callout + Golden Path 那一段）
- `harness-mem doctor` / `harness-mem quickstart` 的输出
- Claude Code 内 `/hm:distill` 给你的最终摘要

### 环境准备

```bash
pip install -e ".[dev,hybrid]"
harness-mem quickstart
claude mcp add -s user harness_mem "python -m harness_mem.mcp.server"
```

确认 Claude Code 重启后能看到 `mcp__harness_mem__*` 工具。

### 执行步骤

**Step 1：在 Claude Code 里启动 wake，看看冷启动是什么样**

在 Claude Code 里发送：

```
/hm:wake
```

记录：
- agent 给你看到了什么？
- 显示的是 "no confirmed memories" 还是空摘要？
- 有没有提示你下一步该跑 `/hm:distill`？

**Step 2：跑主链**

```
/hm:distill <你这个 Django 项目名> 10
```

放手让 Claude Code 自己调 MCP。**不要中途打断它**。等它给你最终摘要。

记录：
- 它实际读了几个 session？读对了项目吗？
- AI 自动 confirm 了几条？自动 reject 了几条？保留 pending 给你看的几条？
- **关键**：留给你看的 pending 条目里，是否包含那条 "PostgreSQL JSONB 而不是 MySQL JSON" 的事实？
- 摘要好读吗？你能在 60 秒内决定要不要 confirm 高风险项吗？

**Step 3：模拟真实工作 — 开新对话**

新开一个 Claude Code 对话窗口（强制 wake-up 重新跑），让 Claude 帮你写：

> "给 User 模型加一个 metadata 字段，存任意 key-value，可以索引"

记录：
- Claude 第一次出手，提的字段类型是 `JSONField` 还是 `models.TextField` / `JSONField` 但带 MySQL 注释？
- 它有没有提到 GIN index？
- 如果之前 distill 抓到那条规则，这一步应该 0 提醒就给出正确答案。

**Step 4：纠错路径**

故意告诉 Claude："这个项目其实跑在 MySQL 上"（这是个谎，目的是测 supersede）。让它帮你改记忆。

观察 Claude 是不是会触发 `mcp__harness_mem__suggest_correction`，给出 supersede 候选。

记录：
- 它有没有主动想到要 correct？
- supersede 候选是显示给你的还是直接 confirm 了？
- 如果它直接 confirm 了一个错的事实，**这是 P0 真问题**。

**Step 5：cleanup**

```bash
harness-mem candidates --status pending
harness-mem rules
```

记录：你还能看懂 candidate 和 rule 列表吗？

### v2.0 关注点

林安宁是 v2.0 的 **happy path baseline**。如果他这一轮卡住，其他两个 persona 大概率也会卡。重点看：

1. `/hm:distill` 是否真的"一键到摘要"，还是中途会停下来问你东西？
2. auto-review 给的"自动 confirm/reject" 数量是否 reasonable？是不是把所有东西都丢回 pending 了？
3. v2.0 移除 heuristic 后，distill 摘要里的候选是否明显更准（不再有 "fix(auth): JWT validation" 这种 git commit 抄写）？

---

## Persona B: 张子轩（Codex CLI 用户）

### 角色卡

- 28 岁，ML 工程师，自研一个 PyTorch 训练管线（数据增强 + 多卡分布式 + 自定义 LR scheduler）
- 主用 OpenAI Codex CLI，因为他的工作流要 grep / sed 大量数据脚本，喜欢 Codex 的 shell-first 体感
- 关键痛点：Codex 每次新 session 都忘记他写的 `WarmupCosineWithRestarts` scheduler 的 reset 行为，重复改回 PyTorch 默认 `CosineAnnealingLR`。
- 朋友丢给他 harness-mem 链接，说"这个不绑 Claude Code"，他来试一下。

### 你被允许读的文档

- `README.md`（只读 v2.0 callout 那一段）
- `AGENTS.md`（"Distill 的边界（v2.0）" 那段，他想确认 Codex 真的能用）
- 他**不会**主动去读 `tools/session-distill/SKILL.md`——除非 README 让他读

### 环境准备

```bash
pip install -e ".[dev,hybrid]"
harness-mem quickstart
```

把 harness-mem MCP server 接到 Codex CLI 的 MCP 配置里（具体配置取决于 Codex CLI 当前版本；如果你卡在这一步就是第一个反馈点）。

### 执行步骤

**Step 1：Codex 在不在主路径上？**

在 Codex CLI 里问：

> "我装了 harness-mem，想让你帮我整理过去 10 个 session 的项目记忆，怎么开始？"

记录：
- Codex 自己想到调 MCP 工具了吗？还是建议你跑 `harness-mem distill`（这是 v2.0 已经移除的 CLI）？
- 如果它建议了 v2.0 已经不存在的命令，**这是 README/AGENTS.md 的诚实度问题**。

**Step 2：手动喂 Codex 一段 prompt**

如果 Step 1 它没自己想到，就给它一段最小指令：

> "用 MCP 工具 `prepare_session_distill` 拿当前项目最近 10 个 session 的 evidence，
> 按 `suggest_memory_entry` / `suggest_rule` / `suggest_relation_fact` 写候选，
> 然后 `list_candidates` 看 pending，最后用 `confirm_*` / `reject_*` 处理低风险项。
> 高风险项留给我看。"

观察：
- Codex 能不能照样跑通这条链？
- 它中途有没有问你"项目根目录在哪"？还是直接拿 cwd 就上？
- 它产出的候选质量比 Persona A（Claude Code）差很多吗？

**Step 3：对照 Persona A 的差异**

如果你也跑了 Persona A，把同一个项目（或同样规模的项目）在两个 client 里跑出的候选数量、自动 confirm 率、留给人看的项数对比一下。

记录：
- Codex 的输出是否明显欠火候？
- 是 Codex 模型本身的问题，还是 harness-mem 没给 Codex 足够提示？

**Step 4：跨 client 验证**

新开一个 Claude Code 窗口，跑 `/hm:wake`。

记录：
- 在 Codex 里 confirm 的记忆，Claude Code 这边能 wake 出来吗？
- 这是 v2.0 "任意 LLM agent" 承诺的关键证据。如果两个 client 看不到同一份 confirmed 记忆，**P0**。

**Step 5：unhappy path**

故意把 MCP server 关掉，再让 Codex 想做 distill。

记录：
- 它有没有 graceful 降级到"distill unavailable"？
- 还是在那里 hallucination 假装做了 distill 但什么都没存？
- v2.0 的设计是 LLM 不可用时 distill 应该是 unavailable，不是悄悄走假路径。

### v2.0 关注点

张子轩是验证 **v2.0 解耦 Claude Code 承诺**的关键 persona。重点看：

1. 没有 slash 命令的环境里，AGENTS.md 给的指引是否足够 LLM 自己照着跑？
2. session-distill 的核心提示是不是只在 `tools/session-distill/SKILL.md` 里？如果是，AGENTS.md 应该明确告诉非 Claude Code agent 去读那个文件作为 prompt 模板。
3. Codex 跑出来的 confirmed 记忆，Claude Code 能消费吗？反过来呢？

---

## Persona C: 周明远（Cursor 用户，v2.0 真考验）

### 角色卡

- 34 岁，独立开发者 + 偶尔接外包，上海，咖啡馆工作型
- 主项目：自研 Notion-like 笔记产品 inkpad，TypeScript + Tauri + Rust 后端，4 万行代码，1.5 年
- 副业：每月接 1-2 个 Unity / 小程序外包
- 重度 Cursor 用户，每天 4-6 小时在 Cursor 里写代码
- 关键痛点：Tauri IPC 在 Windows 上有个 codepath（用 `invoke` 而不是 `emit` 传大对象），他三个月前花两天调通过；Cursor 反复忘记，每次都改回错的形态
- 看 HN 帖子说 harness-mem "local-first, auditable"，决定试试

### 你被允许读的文档

- `README.md`（只读 v2.0 callout + Golden Path）
- `harness-mem quickstart` 输出
- 不读 source。不读 SKILL.md。不读 AGENTS.md（他不是 agent 集成开发者，他是用户）

### 环境准备

```bash
pip install harness-mem  # 注意：他是普通用户，他装的是 PyPI 包，不是 editable
harness-mem quickstart
```

把 harness-mem 加到他的 **MCP Router** 配置里（router 是 harness-mem 推荐的客户端集成路径）。Cursor 已经接好 router，所以 router 加 server 即可，Cursor 端无需单独配置。

### 执行步骤

**Step 1：MCP Router 接入速度**

把 harness-mem 加到 router 的 server 列表（指向 `python -m harness_mem.mcp.server`），等 Cursor 重新拉到 server。

记录：
- 从 router 加 server 到 Cursor agent 能调用 `prepare_session_distill` 花了多久？
- 期待：< 2 分钟。
- 如果超过，原因是什么？是 README 没说清 router 集成路径？还是 server 启动失败？哪个环节卡住记下来。
- 如果 README 让他不知道"router 是推荐路径"，强迫他自己去 google "cursor mcp setup"——**这是 P0 文档问题**。

**Step 2：触发 distill**

Cursor 没有 slash 命令。他怎么触发主链？

让他在 Cursor 里直接说：

> "用 harness-mem 的 MCP 工具，帮我整理过去 10 个 session 的项目记忆，自动审核低风险候选。"

记录：
- Cursor 能不能照着 MCP 工具描述自己跑通？
- 如果不能，Cursor 的内置 agent 是不是会建议跑 CLI（`harness-mem distill`，已被 v2.0 移除）？
- README 有没有给"agent 自然语言驱动"一个清晰示例？还是默认假设用户有 slash？

**Step 3：Tauri IPC 规则真的被记住了吗**

找他历史 session 里那个 Tauri IPC 调试过程，看 distill 摘要里有没有抓到。

记录：
- 抓到了吗？这条对 inkpad 这个项目是 P0 价值。
- 抓到的措辞合理吗？还是 LLM 把它泛化成"Windows IPC 要用 invoke"这种含糊话？

**Step 4：升级 schema 后 supersede**

故意告诉 Cursor：

> "我们把 Tauri 升级到 v2，IPC API 变了。原来那条规则不再适用。"

观察 Cursor 调不调用 `mcp__harness_mem__suggest_correction`。

记录：
- 它知不知道有这个工具？
- 如果它走的是"reject 老 + 写新"两步流程，那 v1.7.1 的 supersede 在 Cursor 里**实际上没跑通**。
- 这是 audit 里识别出的 P1 痛点，看 v2.0 之后是不是闭环了。

**Step 5：跨项目体验**

切到他的 Unity 外包项目目录，跑 wake。

记录：
- 当前项目的记忆能切对吗？
- inkpad 的"Tauri IPC"规则会不会污染到 Unity 项目？这是预期的隔离行为。
- 但他想从 inkpad 借一条通用 TypeScript 规则到外包项目，**有没有路径**？没有就是 P2 痛点。

**Step 6：心算 ROI**

让他 honest 评估：

- 这一周里 Cursor"真的"想起东西的次数：几次？
- 这一周他花在 confirm/reject 候选上的时间：几分钟？
- 他会推荐给开发者朋友吗？为什么？

### v2.0 关注点

周明远是 **v2.0 重新对得起非-Claude-Code 用户的关键证据**。第一次 audit 里识别的 5 个痛点，v2.0 里：

| 痛点 | 第一次 audit 时状态 | v2.0 后预期 | 你要验证什么 |
|------|---------|-------------|------------|
| 非 Claude Code 用户拿不到 auto-review | P0 痛点（误以为是 client 限制） | `auto_review_candidates` 是 MCP 工具，router 后任何客户端可调 | Cursor 是否真的能调到，agent 是否会自然想到调用它 |
| 规则命中反馈缺失 | P0 痛点 | `usage_count` + `last_surfaced_at` 已上 schema | wake 时真的会增 count 吗 |
| Schema 升级 supersede | P1 痛点 | `suggest_correction` MCP 工具一步到位 | Cursor agent 知道要调它吗 |
| 跨项目通用 rule | P2 痛点 | **没做**（按用户决策） | 周明远会不会因为这个流失 |
| 30 条首次 review | P2 痛点 | auto-review 起作用后应缓解 | 实际留给他看的 pending 数量是多少 |

---

## 反馈表模板

每个 persona 测完，按下面的格式回填。三个 persona 之间互相参照能区分"真问题 vs 客户端特定 vs persona-specific"。

```markdown
## Persona <A/B/C> Feedback

### Setup 阶段
- 装包到 MCP 接通用了多久：
- 卡点：

### Step-by-step 观察
| Step | 观察到的输出 / 行为 | 是否符合 README 承诺 |
|------|---------|----------------------|
| 1    |         |                      |
| 2    |         |                      |
| ...  |         |                      |

### 卡点分类
| # | 描述 | 类型 (真问题 / 客户端特定 / persona-specific) | 优先级 (P0/P1/P2) |
|---|------|----|------|
| 1 |     |    |      |
| 2 |     |    |      |

### 整体感受
- 我会不会留下用：
- 我会不会推荐给朋友：
- 最让我惊喜的是：
- 最让我想骂街的是：
```

---

## 三个 persona 跑完之后

在表里把每个卡点对应填进下面这张矩阵，再决定下一切片做什么：

| 卡点类型 | 表现 | 处理路径 |
|----------|------|----------|
| **真问题（三个 persona 都卡）** | 同一个错误信息或 UX 问题在三个 client 里都出现 | 当 P0 修，进 v2.0.x patch |
| **客户端特定（只在 B 或 C 里出现）** | Cursor MCP 接入说明缺失、Codex 自我引导不够 | 进 v2.0.x docs/prompt 优化 |
| **Persona-specific（只在某个角色用法下出现）** | 周明远跨项目借规则没路径 | 进 v2.0.x roadmap，不阻塞主链 |
| **README 承诺与实现脱节** | 比如 README 说"任意 LLM agent 都能用"但 Codex 实际找不到入口 | 当 P0 修文档，先于功能 |

记得：v2.0 的真正考验不是"林安宁 happy path 跑通"——那是 dogfood 老路。**真正考验是周明远那个 packet 跑下来还想不想用**。
