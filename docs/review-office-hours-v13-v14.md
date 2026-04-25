# YC Office Hours: harness-mem

> Partner: 直说，不绕。以下六问，不留情面。

---

## 1. 痛点有多大？

**我的判断：痛，但不至于嗷嗷叫。**

"我不记得上次 Claude 跟我说了什么" — 这是真问题。Claude Code session 之间无记忆，每次重新开始就得重新交代 context。但问题是：**用户不记得不等于用户愿意付费解决。**

当前用户的 bypass：（1）一个 session 里干完所有事；（2）关键信息写进 CLAUDE.md；（3）接受遗忘，每次都重新解释。这三种方案成本都不高，而 harness-mem 需要用户主动安装、学习、维护。要让用户从"不完美但免费"切换到"需要我付时间成本"，疼痛阈值必须高一个数量级。

**结论：pain is real but mild.** 要商业化，要么找到痛到流血的细分场景，要么把安装到产出价值的路径压到 30 秒内。

---

## 2. 用户是谁？

**Claude Code + Codex 开发者 — 既是机会也是陷阱。**

- **机会：** 这群人懂 CLI、懂 MCP、懂 pip install。学习曲线他们爬得动。
- **陷阱：** 这群人也**最能自己搭方案**。他们会说"写个 post-session 脚本把日志倒进 SQLite 不就完了？" 你不仅要比他们手搓的方案好，还要好到值得他们放弃控制权。
- **市场大小：** Claude Code + Codex 日活用户目前还算小众。V1 没问题 — 你该服务好早期传教士。但 V2 要考虑：产品只服务 AI 开发者，还是能外溢到 Cursor/Windsurf 的普通开发者？

---

## 3. 魔法在哪里？和直接问 Claude"你还记得吗"有什么区别？

**翻译一下问题：如果我就打开 Claude Code 直接问，和你这个 MCP server 有什么区别？**

区别在于：**Claude 的记忆是 session-scoped 且 opaque 的。** 当前 session 的上下文窗口满了就被丢弃，CLAUDE.md 只能手写、不会自我演化。harness-mem 的定位是 **long-term, structured, queryable memory** — 不在当前 context window 里的东西，通过检索拿回来。

但这个区别目前还不够锐利。用户感知到的"魔法"应该是：**打开新 session，Claude 自动知道上周做了一半的 feature 是啥、卡在哪、用什么方案。** 如果 harness-mem 今天还不能稳定交付这个体验，那你卖的不是魔法，是工具链。

**差异化在于闭环完成度：** ingest → correct → learn → resume。如果这个闭环跑不通，那确实不如直接问。

---

## 4. 是产品还是 feature？

**扎心的问题。我的答案：目前是 feature。**

如果 Claude Code 官方明年做一个事：在 settings 里加一个 toggle"Enable long-term memory"，用户选上就能自动跨 session 延续上下文 — harness-mem 今天 80% 的价值就被内置了。Anthropic 产品团队不是傻子，跨 session memory 是 Claude Code 的 obvious next step。

**你的 moat 在哪里？**
- **Local-first 和隐私：** 有人就是不想把记忆交给云端。数据永远在本地 SQLite，这是差异化。
- **Multi-client：** Claude Code + Codex + 未来其他 AI 客户端共享同一套记忆。Claude 官方做的是 Claude-only memory，你做的是 runtime。
- **可编辑/可审计：** 用户能 search、correct、delete。官方 memory 通常是黑箱。

三个加起来是 thin moat。不够宽，但足够多的 privacy-sensitive 团队用户的话，也不窄。

**生存策略：** 不和官方拼 feature 密度，拼 integration breadth + data ownership。

---

## 5. 抽象层对吗？CLI + MCP server？

**CLI 对早期开发者用户来说是对的。MCP server 是合理的平台桥梁。**

但我要 challenge 一个点：**你的用户真的想要一个 CLI 来管理记忆吗？** 大多数开发者打开 Claude Code 是为了写代码，不是为了跑 `harness-mem ingest` 和 `harness-mem wake`。

CLI 是好的 bootstrap — 开发者熟悉 CLI，pip install 就能试。但长期来看，harness-mem 需要变得 invisible：

- **首选形态：** Claude Code 打开时自动加载 MCP server，自动 ingest、自动 wake。用户无需主动操作。
- **备选形态：** VS Code extension + daemon 后台跑。用户只感知到"这个 Claude 记住我了"，看不到 harness-mem 在运行。
- **不应做的：** LSP server — 和你们的问题域不匹配。

当前 CLI + MCP 是合理的 **entry point**。但如果 V2 还要求用户手动敲命令来管理记忆，说明 abstraction 还不够。

---

## 6. 10x 版本是什么？

如果 harness-mem 变得无比成功，它不会是一个"记忆搜索工具"。它会变成：

**Agent Memory Runtime — AI 操作系统的持久化层。**
- 不只是存文本记忆，而是存 agent 的 belief state、decision graph、skill library
- 不只是 Claude Code，任何 AI agent（GitHub Copilot、Cline、自定义 agent）都通过统一协议读写
- 不只是"记得过去"，而是"能推理过去 → 规划未来" — 带时间线的 agent brain

**当前路线图的 gap：**
- V1 是 ingest + search，这是"归档"，不是"运行时"
- V2 的 hybrid retrieval + 学习闭环在往 runtime 方向走，但还缺 **主动写**（agent 自己决定存什么）和 **主动推**（在合适时机把记忆注入 context，而不是等用户 search）
- 10x 版本应该是：打开新 session，harness-mem 后台自动决定这个 session 需要知道什么，静默注入。你从来不需要手动 search。

**距离 10x 多远？**
V1 → 10x 大概隔了 2-3 个 major 版本。从"用户驱动的记忆工具"到"agent 驱动的记忆运行时"，每次都需要重思谁是控制主体。

---

## 总结：Partner 的 verdict

| 问题 | 判断 |
|------|------|
| 痛点 | True but mild |
| 用户 | 早期正确，需规划外溢 |
| 魔法 | 闭环未完全跑通前不够锐利 |
| Product vs Feature | 目前是 feature，moat thin |
| 抽象层 | CLI + MCP 合理，需朝 invisible 演进 |
| 10x vision | 明确且宏大，路线图还有 gap |

**建议：** 找 5-10 个每天用 Claude Code 的团队，把 harness-mem 装进日常工作流，观察（a）有没有形成习惯、（b）在哪一步放弃、（c）谁主动说"这个功能省了我 X 时间"。拿到这些数据前，不要过早讨论 pricing。
