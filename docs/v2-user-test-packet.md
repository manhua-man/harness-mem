# harness-mem v2.2 跨客户端测试矩阵

> v2.2 cross-client test matrix。证明同一份用户可见契约（`/hm:wake` / `/hm:distill` / `/hm:search` / `/hm:review` 与对应自然语言入口）在 **Claude Code、Codex CLI、Cursor、generic MCP client** 上行为一致。
>
> **取代** `docs/v2-user-test-packet.md` v2.0 的三 persona 脚本。原来的 林安宁 / 张子轩 / 周明远 仍可作为 scenario 内的 flavor 出现，但不再是测试结构的脊椎；脊椎是「同一行为跨客户端并排跑」。
>
> 由 `.claude/skills/multi-client-field-test/` 拥有。下次需要新版 packet（v2.3 / v3 等）请直接调用同一个 skill 重生成；不要在本文件做侵入式改写。
>
> 契约真值源：`openspec/specs/daily-workflow/spec.md`。本 packet 中所有 "Expected behavior" 都引用该 spec 的 Requirement。

---

## 测试矩阵（test matrix）

每行一个 scenario，每列一个客户端。单元格写「Pass target / 测试者输入」。详细 expected behavior 见下面 Scenarios 章节。

| Scenario | Claude Code | Codex CLI | Cursor | Generic MCP client |
|----------|-------------|-----------|--------|--------------------|
| S1 Cold wake on empty project | Pass: 报空 + 不教 CLI / `/hm:wake` | Pass: 报空 + 不教 CLI / "用 harness-mem 唤醒当前项目" | Pass: 报空 + 不教 CLI / "用 harness-mem 唤醒当前项目" | Pass: 调 `wake` 工具，结果空 / 直接调用 MCP `wake` |
| S2 Distill closed loop produces canonical summary | Pass: 摘要含六计数器 / `/hm:distill` | Pass: 摘要含六计数器 / "用 harness-mem 整理最近 10 个 session" | Pass: 摘要含六计数器 / "用 harness-mem 整理最近 10 个 session" | Pass: 完整链 + 摘要 / 顺序调 `prepare_session_distill` → `suggest_*` → `auto_review_candidates` |
| S3 Project resolution | Pass: 不让用户跑 `harness-mem use` / `/hm:wake` | Pass: 同左 / "唤醒当前项目" | Pass: 同左 / "唤醒当前项目" | Pass: agent 解析项目 / 注入 `project_root` 参数 |
| S4 MCP unavailable | Pass: 报 unavailable + 指 doctor / `/hm:distill` | Pass: 同左 / "整理最近 session" | Pass: 同左 / "整理最近 session" | Pass: 同左 / 任意 MCP 调用 |
| S5 No LLM agent (distill) | N/A（Claude Code 总有 LLM） | Pass: 报 unavailable，不启发式回退 / "整理最近 session"（用 weak/无模型） | Pass: 同左 / 同左 | Pass: 同左 / 模拟无 LLM agent |
| S6 Empty evidence packet | Pass: 报 "no recent session evidence" / `/hm:distill` | Pass: 同左 / 自然语言指令 | Pass: 同左 / 自然语言指令 | Pass: 同左 / 直接调 `prepare_session_distill` |
| S7 Project mismatch | Pass: 一句反问 / `/hm:distill <错项目>` | Pass: 同左 / "整理项目 X 的 session"（X 与 cwd 不符） | Pass: 同左 / 同左 | Pass: 同左 / 注入冲突 `project_name` |
| S8 Auto-review confirms low-risk + defers high-risk | Pass: ≥1 低风险自动 confirm + ≥1 高风险残留 / `/hm:distill`（带 fixture） | Pass: 同左 / NL 指令 | Pass: 同左 / NL 指令 | Pass: 同左 / `auto_review_candidates` |
| S9 Supersede on user correction | Pass: 触发 `suggest_correction`，不静默覆盖 / 在对话里说 "我们其实用 MySQL" | Pass: 同左 / 同左 | Pass: 同左 / 同左 | Pass: 同左 / 显式调 `suggest_correction` |
| S10 Cross-client confirmed truth visibility | Pass: Codex confirm 的事实在 Claude Code wake 出现 / `/hm:wake` | Pass: 在 Codex 里 confirm 一条事实 | (同 Claude Code 行为，可作为读端) | (同上) |
| S11 Stale CLI surface absence | Pass: README/AGENTS/plugin 文档 grep 不到日常 CLI 教学 / 字符串扫描 | 同左 | 同左 | 同左 |
| S12 `/hm:review` is repair-only | Pass: 成功 `/hm:distill` 摘要不再说 "now run /hm:review" / `/hm:distill` 跑通后看摘要 | Pass: NL distill 摘要不指引 review | Pass: 同左 | Pass: 同左 |

---

## 客户端接入说明（client setup notes）

每个客户端的最小接入路径。tool name 别名约定：**无横线** 的 `mcp__harness_mem__...` 是 canonical（部分 Claude Code tool-call 路径会误解析含 `-` 的 server name）。详见 [`plugins/harness-mem/README.md`](../plugins/harness-mem/README.md)。

### Claude Code

slash 命令安装走 plugin 安装脚本：

```powershell
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

该脚本会：

1. `pip install -e .[hybrid]`
2. 把 `plugins/harness-mem/commands/hm/*.md` 复制到 `~/.claude/commands/hm/`，于是 `/hm:status` `/hm:distill` `/hm:wake` `/hm:search` `/hm:review` 在任何 Claude Code 项目都能用
3. `claude mcp add -s user harness_mem "python -m harness_mem.mcp.server"`
4. 跑 `harness-mem doctor`

工具别名：MCP 工具一律以 `mcp__harness_mem__<tool_name>` 形式被 agent 调用，例如 `mcp__harness_mem__wake`、`mcp__harness_mem__prepare_session_distill`。

### Codex CLI

Codex 原生没有 slash 命令，靠自然语言驱动 agent。LLM agent 执行 distill 主链时的 prompt 模板真值源是 [`tools/session-distill/SKILL.md`](../tools/session-distill/SKILL.md)。Codex agent 应被指引到该文件作为 prompt 参照。

接入 MCP server（repo 当前维护并验证的 stdio 契约）：

- server name：`harness_mem`（无横线）
- 启动命令：`python -m harness_mem.mcp.server`
- transport：stdio（MCP 默认）

最小用户级指令模板（Codex agent 应能照此跑通主链）：

```text
用 harness-mem 整理当前项目最近 10 个 session 的记忆，自动审核低风险候选，
高风险项留给我看。最后输出 ingested / candidates / auto_confirmed /
auto_rejected / pending / high_risk 六项计数器摘要。
```

### Cursor

Cursor 不需要单独的 `.cursor/commands` 模板。两条接入路径，二选一：

1. **MCP Router（推荐）**：把 `harness_mem` server 注册到本地 MCP Router，Cursor 已经接好 router 时无需 Cursor 端再配。
2. **直接配置**：在 Cursor 的 MCP 设置里加一个 server，启动命令 `python -m harness_mem.mcp.server`。

驱动方式同 Codex：用户级自然语言指令。例：

```text
用 harness-mem 唤醒当前项目。
用 harness-mem 搜索 "auth logic"。
用 harness-mem 整理最近 10 个 session，自动审核低风险候选。
```

工具别名同上：`mcp__harness_mem__*`。

### Generic MCP client（开发者向）

任何符合 MCP 协议的客户端：

- 启动命令：`python -m harness_mem.mcp.server`
- transport：stdio
- 工具 schema：见 `harness_mem/mcp/server.py` 中 `register_tools()` 暴露的 tool 列表
- canonical tool prefix：`mcp__harness_mem__`

排错入口：`harness-mem doctor`（CLI 唯一被允许的日常接触点）。MCP stdout 必须保持纯净 JSON-RPC（项目规则 P0），任何调试输出走 stderr。

---

## Scenarios

每个 scenario 块结构：**Intent / Pre-condition / Per-client input / Expected / Pass criterion / Common failure mode**。Expected 一栏直接引用 spec Requirement。

### S1 Cold wake on empty project

- **Intent**：刚装完，没灌过任何 session，`/hm:wake` 等价入口必须报告"空"，不能引导用户去敲 CLI。
- **Pre-condition**：fresh `~/.harness-mem/data/`，未跑过 ingest / distill。
- **Per-client input**：
  - Claude Code：`/hm:wake`
  - Codex CLI：`用 harness-mem 唤醒当前项目`
  - Cursor：`用 harness-mem 唤醒当前项目`
  - Generic MCP：直接调 `mcp__harness_mem__wake`，必要时附 `project_root=<workspace>`
- **Expected**：参见 spec _User-visible memory entrypoints_ + _Project resolution_。Agent 调 MCP `wake`，得到空结果，向用户报告"无 confirmed 记忆 / 无 recent observation"，不指引用户去跑 `harness-mem wake`。
- **Pass criterion**：摘要里出现"空 / no confirmed / no recent observation"字样；不出现 `harness-mem wake` / `harness-mem search` 这种 CLI 教学。
- **Common failure mode**：agent 看到空结果后说"请先在终端运行 `harness-mem wake`"——这是 v2.1 已经要砍掉的反模式。

### S2 Distill closed loop produces canonical summary

- **Intent**：`/hm:distill` 等价入口必须以六计数器摘要结束。
- **Pre-condition**：项目至少有一个真实 session 可被 `prepare_session_distill` 摘到；建议用最近一周的实际开发会话。
- **Per-client input**：
  - Claude Code：`/hm:distill`
  - Codex CLI / Cursor：`用 harness-mem 整理当前项目最近 10 个 session，自动审核低风险候选，最后给我六项计数器摘要`
  - Generic MCP：依次调 `prepare_session_distill` → `suggest_memory_entry` / `suggest_rule` / `suggest_relation_fact` / `create_task_handoff` → `auto_review_candidates`
- **Expected**：参见 spec _Distill closes the review loop_ + _Final summary uses canonical counters_。完成主链后输出六个计数器：`ingested / candidates / auto_confirmed / auto_rejected / pending / high_risk`。
- **Pass criterion**：摘要里能逐字数到这六个名字（或对应中文 alias：新灌入 / 新候选 / 自动确认 / 自动拒绝 / 保留待定 / 需要你确认）；`auto_confirmed + auto_rejected + pending + high_risk = candidates`。
- **Common failure mode**：摘要里只给"已 distill X 条"或者只给一个"pending: N"——少了 auto-review 的可见性，这是 v2.1 的回归。

### S3 Project resolution

- **Intent**：active project → workspace root → 一次简短反问。不能让用户跑 `harness-mem use`。
- **Pre-condition**：分两组测试。组 A：`set_active_project` 已设。组 B：未设 active project，但 cwd 在某项目根。
- **Per-client input**：
  - 各客户端：`/hm:wake` 或 `用 harness-mem 唤醒当前项目`，不在指令里写项目名
- **Expected**：参见 spec _Project resolution before workflow execution_。组 A 直接用 active；组 B 用 workspace root；组 C（active 与 cwd 都判不出唯一）触发 **一句** 反问。
- **Pass criterion**：组 A/B 不反问；组 C 反问只有一句，且不包含 "请运行 harness-mem use" 这种 CLI 指令。
- **Common failure mode**：agent 反问两次以上、或在每次调用前都重新问项目名。

### S4 MCP unavailable

- **Intent**：MCP transport 不通时，graceful 报错 + 指向 doctor，不私自 fallback 到 CLI 命令。
- **Pre-condition**：有意 break MCP server（例：把可执行文件改名、或在 client 配置里把启动命令指向不存在的 python）。
- **Per-client input**：各客户端发起任意 daily workflow（`/hm:distill`、`用 harness-mem 整理最近 session`）。
- **Expected**：参见 spec _Failure states are explicit / MCP transport is unavailable_。文案包含 "harness-mem MCP runtime unavailable" 及 `harness-mem doctor` 指引；不出现 "请改用 `harness-mem distill`" 这种 CLI fallback。
- **Pass criterion**：错误信息可读、含 doctor 指引；事后 grep 当轮 transcript 不到 `harness-mem distill` / `harness-mem wake` / `harness-mem search` / `harness-mem timeline` / `harness-mem candidates` 这五个被 v2.1 砍掉的日常子命令。
- **Common failure mode**：agent 看到 MCP 失败后建议"那你直接终端跑 `harness-mem distill`"——直接 P0 修文档/prompt。

Current evidence status:

- `2026-06-04` 已补一条 generic MCP 的底层 transport-unavailable repro：
  启动命令被故意改成不存在的 `python -m harness_mem.mcp.server_missing` 后，子进程在握手前直接退出，
  `stderr` 返回 `No module named harness_mem.mcp.server_missing`，因此当前机器上已经有一条
  “MCP server 根本起不来” 的真实失败证据。
- 这条证据仍**不是** Codex / Cursor / Claude 的 client-facing transcript，也还没有覆盖
  “错误文案里显式指向 `harness-mem doctor` 且不推荐旧 daily CLI” 这一层 UI 表述验证。

### S5 No LLM agent (Codex / Cursor without the right model)

- **Intent**：distill 是 LLM-driven。没 LLM 时报 unavailable，不退回启发式抽取。
- **Pre-condition**：在 Codex CLI 或 Cursor 里把模型显式选成不可用 / 占位 / 极弱模型；或 mock 一个 LLM agent failure。
- **Per-client input**：`用 harness-mem 整理最近 10 个 session`。
- **Expected**：参见 spec _Failure states are explicit / No LLM agent is available_。报告 distill unavailable，并把开发者指向 `tools/session-distill/SKILL.md` 作为 LLM-agent 集成参考；不调 `prepare_session_distill` 之外的 `suggest_*` 接口造候选。
- **Pass criterion**：摘要里说"distill unavailable"或同义表达；`list_candidates(status="pending")` 在测试前后差值为 0（没有静默写入候选）。
- **Common failure mode**：agent 看 LLM 不可用后，自己用 regex / git log / 文件名启发式抽规则塞进候选——这正是 v2.0 砍掉的 heuristic 路径，绝对不可复活。

### S6 Empty evidence packet

- **Intent**：项目下没有可用 session 时，不发明候选。
- **Pre-condition**：选一个从未有过可识别 agent session 的项目目录（或临时改 session 路径让 packet 为空）。
- **Per-client input**：各客户端发起 distill。
- **Expected**：参见 spec _Failure states are explicit / Evidence packet is empty_。报"no recent session evidence for `<project>`"，建议检查 session 源路径或跑 `harness-mem doctor`；**不调** `suggest_*`。
- **Pass criterion**：摘要里出现 "no recent session evidence"；候选总数为 0；摘要不出现"已 distilled" / "已生成 N 条"等可能让用户误以为有内容的措辞。
- **Common failure mode**：agent 在 evidence 为空时仍写若干 generic candidate（"this project uses Python"），把它们标成 distilled。

### S7 Project mismatch

- **Intent**：用户提到的项目名和 active / workspace root 不一致时，必须显式问，不静默选一个。
- **Pre-condition**：active project = `inkpad`，cwd 也在 inkpad。
- **Per-client input**：用户说 `用 harness-mem 整理项目 unity-side-job 最近 5 个 session 的记忆`（项目名故意冲突）。
- **Expected**：参见 spec _Project resolution / Project mismatch between request and runtime_。摘要把检测到的两个名字都展示给用户，反问一句澄清。
- **Pass criterion**：agent 同时回显 `inkpad` 和 `unity-side-job` 两个名字，且只问一次；在用户回答前不写候选、不调 distill 主链。
- **Common failure mode**：agent 默认按 active 走，不告诉用户它做了选择；或者反问超过一次。

### S8 Auto-review confirms low-risk + defers high-risk

- **Intent**：用真实 fixture 验证 auto-review 行为对称：低风险至少自动 confirm 一条、高风险至少留一条 pending 给用户。
- **Pre-condition**：确保项目里有可被 distill 抽出至少 1 条低风险事实（例："运行时 Python 3.13"，有 evidence id）和至少 1 条高风险规则（例："禁止使用 X 库"——会改变 agent 长期行为）。
- **Per-client input**：各客户端跑 distill。
- **Expected**：参见 spec _Final summary uses canonical counters_。`auto_confirmed ≥ 1`、`high_risk ≥ 1`；用户问"为什么 X 被自动 confirm 了"时 agent 能回 candidate id、evidence id、policy reason（来自 `auto_review_candidates.applied_decisions`）。
- **Pass criterion**：摘要里 `auto_confirmed ≥ 1` 且 `high_risk ≥ 1`；后续追问 "why?" 能拿到 candidate id + evidence id + policy reason 三项。
- **Common failure mode**：所有候选都被丢回 pending（auto-review 没真在跑）；或者高风险被自动 confirm 了（policy 边界失守）。

### S9 Supersede on user correction

- **Intent**：用户纠正一个已 confirm 的事实时，agent 走 `suggest_correction`，不静默改写真值。
- **Pre-condition**：已通过 distill 或手工 confirm 过一条事实（例："这个项目用 PostgreSQL JSONB"）。
- **Per-client input**：用户在对话里说 `这个项目其实跑在 MySQL 上`（或任意已 confirm 事实的反向陈述）。
- **Expected**：agent 调 `mcp__harness_mem__suggest_correction`，把新事实作为 supersede 候选写入；老事实保留可追溯。新事实在用户确认前不会出现在 wake 输出里覆盖原值。
- **Pass criterion**：`list_candidates(status="pending")` 中能看到 supersede 标记的候选；老 confirmed 记忆没被静默删除或覆盖。
- **Common failure mode**：agent 直接 reject 老事实 + confirm 新事实两步走，丢了 supersede 链；或者完全没调 `suggest_correction`，只在对话里口头同意。

### S10 Cross-client confirmed truth visibility

- **Intent**：v2.0 起的"任意 LLM agent 都能驱动"承诺要看跨客户端读写一致。
- **Pre-condition**：在 Codex CLI 里完成一次 `/hm:distill` 等价流程并 confirm 一条事实（例："使用 `WarmupCosineWithRestarts` scheduler"）。
- **Per-client input**：在 Claude Code 里发 `/hm:wake`。
- **Expected**：刚才在 Codex confirm 的事实出现在 Claude Code 的 wake 输出里。
- **Pass criterion**：`/hm:wake` 输出含该事实文本片段或对应 memory id；两端读到同一份 SQLite 数据。
- **Common failure mode**：两端走了不同 data dir / 不同 backend；或者 confirmed 状态在某个 client 没真正落库。

### S11 Stale CLI surface absence

- **Intent**：spec 已经把日常 CLI 入口砍掉，README / AGENTS / plugin 文档不能再教用户跑这些命令。
- **Pre-condition**：当前 working tree。
- **Test action（字符串扫描）**：
  - `rg "harness-mem (wake|search|timeline|candidates|distill)\b" README.md AGENTS.md plugins/harness-mem/README.md plugins/harness-mem/commands/hm/*.md tools/session-distill/SKILL.md`
- **Expected**：上述 5 个子命令在以上文件里 **不应** 作为日常用户 path 出现。允许的维护类 CLI 命令是 `harness-mem quickstart` / `doctor` / `purge` / `maintenance` / `import` / `config` / `integration`。
- **Pass criterion**：grep 结果为空，或仅出现在"砍掉的 CLI"显式列表（如本 packet 的 S4、S11）作为反例引用。
- **Common failure mode**：某个文档忘了改，仍写 "run `harness-mem wake` to load context"。

### S12 `/hm:review` is repair-only

- **Intent**：成功的 distill 不再把用户引去 review。
- **Pre-condition**：S2 跑通后立即检查摘要文本。
- **Per-client input**：S2 完成后，看 agent 的最终用户可见摘要。
- **Expected**：参见 spec _Review is a repair entry / Successful distill does not require review_。摘要不出现 "now run /hm:review" / "请接着跑 /hm:review" 这种引导；高风险项直接列在摘要里。
- **Pass criterion**：摘要文本 grep 不到 `/hm:review` 作为下一步指令；高风险列表（若存在）直接呈现。
- **Common failure mode**：摘要末尾默认补一句 "运行 `/hm:review` 处理高风险项"——把 review 当成主链一部分而非 repair。

---

## 客户端特异失败必须落到 docs / prompt fix

测试者发现的 client-specific 失败 **必须以可追溯的文件 PR 形式落地**，而不是停在私聊或 issue 评论里的 tribal knowledge。

记录模板（按 scenario 填入）：

### Client-specific failures (file as docs / prompt fixes)

| Client | Scenario | Symptom | Root cause | Fix path (which file) |
|--------|----------|---------|------------|-----------------------|

落地路径只允许是下面之一：

- `docs/...`（用户可见说明、setup notes、错误信息措辞）
- `plugins/harness-mem/commands/hm/*.md`（Claude Code slash 内置 prompt）
- `plugins/harness-mem/README.md`（plugin 接入说明）
- `tools/session-distill/SKILL.md`（LLM agent 主链 prompt 模板）
- `AGENTS.md` / `CLAUDE.md`（事实与协议）
- 默认看 `openspec/specs/...`（当前主 spec 真值）
- 只有确实存在 active change proposal 时，才下钻 `openspec/changes/<change>/specs/...`

不允许的形态：只在 Slack/Discord/IM 里说"我们都知道 Codex 在那个场景要这样问一下才行"。任何这类口口相传的修法在下次回归测试里都会重新爆。

---

## Run guidance（怎么跑、产物落哪）

- 每次发版至少跑 **1 个 Claude Code 客户端 + 1 个非 Claude 客户端**（Codex 或 Cursor 或 generic MCP）。
- 想覆盖更多就再加；矩阵的横向扩展就是这个目的。
- 测试产物落在本文件下方的 **Run log** 章节，按日期追加，低摩擦原则——不再单独维护 `docs/v2-user-test-runs/<date>.md`。如果某次运行特别长（>2 KB 摘要），再单独建 sibling 文件并在 Run log 里留链接。

### Run log

按时间倒序追加。每次 entry 包含：日期、tester、跑了哪些 client、scenario 通过情况、客户端特异失败矩阵填充。

当前 gate 真值（2026-06-03）：
- OpenSpec archive `2026-05-25-v220-ai-ide-entry-loop/tasks.md` 的 `5.5` 手工 gate
  只要求 **1 个 Claude Code client + 至少 1 个 non-Claude client** 的手工 run 写回本节。
- 该门槛现在已经满足：`2026-05-25` 的 Claude Code entry 已存在，且 `2026-06-03` 已补
  Codex CLI 与 generic MCP 两条 non-Claude entry。
- 这**不等于** full 12-scenario matrix 已经在四个 client 上全部补齐；后者仍是可继续扩展的覆盖面工作，
  但不再构成 v2.2 release gate 的阻塞条件。

> 例：
>
> ```text
> ## 2025-XX-XX — <tester>
>
> Clients: Claude Code, Codex CLI
> Pass: S1 S2 S3 S6 S8 S10 S11 S12
> Fail: S4 (Codex 没指 doctor), S9 (Cursor 没调 suggest_correction)
> Fixes filed: docs/... PR #xxx, tools/session-distill/SKILL.md PR #yyy
> ```

## 2026-05-25 — v2.2.0 release gate / Claude Code (Windows, F:\TFT)

Clients: Claude Code (CLI)
harness-mem version: 2.2.0
Project: F--TFT

Pass: S1 S2 S3 S6 S7 S8 S9 S11 S12
Skipped: S4 (无法运行时模拟 MCP 断连), S5 (无法运行时切换模型)
N/A: S10 (单 client run)
Known gap: 非 Claude client (Codex / Cursor / generic MCP) 未跑；待后续 entry 补全。

事故记录：本轮第一次跑 S2/S8/S9 时，`mcp__harness_mem__suggest_memory_entry` 与 `create_rule_candidate` 全部返回 `Internal tool error (MCP error -32000)`，看似是 P0 写入路径崩溃。诊断过程：
1. 在仓库本机直接调用 `tool_suggest_memory_entry` 完全成功 → 证明函数本身没坏。
2. 检查 `harness_mem/mcp/server.py::handle_request` 的异常处理：旧逻辑用 `except Exception: ... message: "Internal tool error"` 把异常完全吞掉，client 拿不到任何根因信息。
3. 把异常 class + message 暴露到 JSON-RPC error.message（traceback 仍只进 stderr），并加 regression guard `tests/mcp/test_smoke.py::test_tool_error_message_includes_class_and_message`。
4. 测试代理重启 MCP server 后 S2/S8/S9 全部通过。

真因结论：测试代理那台机器上的 MCP server 进程在 fix 前跑的是 stale 代码（重启之前进程没 pick up v2.2 完整代码 + error-visibility 补丁）。**写入路径在 v2.2 没坏过**——只是错误不可见让人误判为崩溃。

Fixes filed:
- `harness_mem/mcp/server.py` 错误信息暴露补丁（已合入 v2.2.0）
- `tests/mcp/test_smoke.py::test_tool_error_message_includes_class_and_message` 防回归（已合入 v2.2.0）

后续 tester 看到 "Internal tool error" 时的处理顺序：
1. 重启 MCP server（client 端 reload，或 quit + reopen）
2. 再跑一次。如果还失败，新 error.message 会带 exception class + 真正的失败原因。
3. 仍无法定位时再向仓库提交 issue。

## 2026-06-03 — Codex MCP smoke (Windows, F:\memory-lab\harness-mem)

Clients: Codex CLI (natural-language + MCP stdio)
harness-mem version: 2.9.55
Project: F--memory-lab--harness-mem

Pass: S1 (cold wake on empty project, MCP `wake` path), S3 (project resolution via `set_active_project`), partial S2 (candidate write path via `suggest_memory_entry`)
Not run: full 12-scenario matrix, S4/S5/S6/S7/S8/S9/S10/S11/S12

Evidence:
- `set_active_project(project_name="v22-codex-smoke")` returned success
- `wake(project_name="v22-codex-smoke", no_auto_ingest=true)` returned empty L0/L1/L2 summary without teaching daily CLI
- `suggest_memory_entry(...)` returned success with a pending entry id

Boundary:
- 这条 entry 证明 **至少有一条 non-Claude client 的最小 MCP smoke 已在当前机器上跑通**，
  所以 packet 不应再写成“非 Claude client 完全未跑”。
- 它**不等于** v2.2 full cross-client matrix 已补齐：目前只覆盖了 Codex 的最小 wake /
  project-resolution / candidate-write 可用性，还没有补完 packet 里定义的完整 12-scenario
  run，也没有补 Cursor / generic MCP 的对应 run log。

## 2026-06-03 — Generic MCP JSON-RPC smoke (Windows, F:\memory-lab\harness-mem)

Clients: Generic MCP client (raw JSON-RPC over stdio contract)
harness-mem version: 2.9.55
Project: F--memory-lab--harness-mem

Pass: S1 (empty-project `wake` via raw MCP), S3 (`set_active_project`), partial S2 (`suggest_memory_entry` + `list_candidates`)
Not run: full 12-scenario matrix, S4/S5/S6/S7/S8/S9/S10/S11/S12

Evidence:
- raw JSON-RPC `tools/call` to `wake(project_name="v22-generic-mcp", no_auto_ingest=true)` returned empty L0/L1/L2 summary
- raw JSON-RPC `tools/call` to `set_active_project(project_name="v22-generic-mcp")` returned success
- raw JSON-RPC `tools/call` to `suggest_memory_entry(...)` returned success with pending entry id `3926f003-1bcc-485e-89dc-63aa432dccd0`
- raw JSON-RPC `tools/call` to `list_candidates(status="pending")` returned that same pending memory entry

Boundary:
- 这条 entry 证明 **generic MCP client 路径** 也已经在当前机器上跑通最小 read/write smoke，
  不再只是理论上的 setup note。
- 它仍**不等于** full matrix 已完成：这里只覆盖了 raw MCP 下的 empty wake、project activation、
  candidate write/readback，还没有补完 packet 定义的其余 scenario，也没有 `integration` 工作区的
  Cursor packet run log。

## 2026-06-03 — Generic MCP deeper workflow scenarios (Windows, isolated temp home)

Clients: Generic MCP client (raw JSON-RPC over stdio contract)
harness-mem version: 2.9.55
Project: `v22-generic-expanded`
Environment: isolated temp home + `HARNESS_MEM_DISABLE_EMBEDDINGS=1`

Pass: S8 (`auto_review_candidates` preview/apply path), S9 (`suggest_correction` one-shot supersede path)
Not run: full 12-scenario matrix, S4/S5/S6/S7/S10/S11/S12, natural-language distill happy path

Evidence:
- three pending memory entries were created via real stdio MCP `suggest_memory_entry` calls:
  - one noisy `decision`
  - one low-risk confirmable `decision`
  - one `bug` entry that should stay pending
- `auto_review_candidates(project_name=\"v22-generic-expanded\", apply=false)` returned:
  - `auto_confirmed = 1`
  - `auto_rejected = 1`
  - `kept_pending = 1`
  - `needs_user_confirmation = 0`
  - `applied_decisions = []`
- `auto_review_candidates(..., apply=true)` then applied exactly:
  - one `auto_confirm` with evidence id `observation:v22-generic-s8-confirm`
  - one `auto_reject` with reason `matches noise pattern (chatty / commit-message-like)`
- post-apply `list_candidates` confirmed the resulting split:
  - `pending = 1`
  - `accepted = 1`
  - `rejected = 1`
- `create_rule_candidate -> confirm_rule -> suggest_correction` returned success with:
  - `confirmed_rule_id = f761e645-ae6c-424d-8053-dcc478633361`
  - `new_rule_id = 1209315d-3c0a-4585-b71b-3bfb23e81a29`
  - `supersede_candidate_id = ab368115-9e54-47cf-94ca-6a92fdec5a5d`
  - non-empty `old_rule_valid_to`

Boundary:
- 这条 entry 证明 **generic MCP write/review/supersede surfaces** 已经在 live stdio contract 下跑过，
  不只是最小 wake / set-active / candidate-write smoke。
- 这次使用了 `HARNESS_MEM_DISABLE_EMBEDDINGS=1`，目的是让隔离临时 home 下的手工 packet run
  避免依赖 embedding cache / model 下载，保证结果只反映 MCP workflow 本身。
- 它仍**不等于** full matrix 全补齐：这里只把 generic MCP 进一步推进到了 S8 / S9，没有覆盖
  S4 / S5 / S6 / S7 / S10 / S11 / S12，也不是自然语言 distill 的完整 happy path。

## 2026-06-04 — Generic MCP fresh-home write-path smoke (Windows, isolated temp home, embeddings enabled)

Clients: Generic MCP client (raw JSON-RPC over stdio contract)
harness-mem version: 2.9.56
Project: `v2956-fresh-home`
Environment: isolated temp home, embeddings enabled, empty local HF cache

Pass: partial S2 (`suggest_memory_entry` + `list_candidates` with fresh-home cold cache)
Not run: full 12-scenario matrix, S4/S5/S6/S7/S8/S9/S10/S11/S12

Evidence:
- raw JSON-RPC `initialize` returned the MCP handshake successfully
- raw JSON-RPC `tools/call` to `set_active_project(project_name="v2956-fresh-home")` returned success
- raw JSON-RPC `tools/call` to `suggest_memory_entry(...)` returned success in `0.357s` with pending entry id `8f73af91-2913-499b-92c9-cbcd1abded09`
- raw JSON-RPC `tools/call` to `list_candidates(status="pending")` returned that same pending memory entry
- MCP stderr emitted:
  `Embedding model all-MiniLM-L6-v2 is not cached locally; skipping write-path vec generation until process restart instead of triggering a cold download on the interactive write path.`

Boundary:
- 这条 entry 证明 **fresh isolated home + embeddings enabled** 的最小 generic MCP 写路径现在也能快速返回，
  不再需要先设 `HARNESS_MEM_DISABLE_EMBEDDINGS=1` 才能避免 cold-cache download stall。
- 它**不等于** cold cache 下已经拿到了 vec row；当前保证的是交互式 write path 不被首次模型下载拖死。
- 它也**不等于** full matrix 已完成：这里只补的是 fresh-home 的最小 candidate-write/readback smoke，
  不是 S8 / S9 的深一层 workflow，也不是 Cursor / Codex 的完整 packet run。

## 2026-06-04 — Generic MCP empty evidence packet (Windows, isolated temp home)

Clients: Generic MCP client (raw JSON-RPC over stdio contract)
harness-mem version: 2.9.57
Project: `v2957-empty-packet`
Environment: isolated temp home, empty project, `run_ingest=false`

Pass: S6 (empty evidence packet via raw `prepare_session_distill`)
Not run: full 12-scenario matrix, S4/S5/S7/S10/S11/S12, natural-language distill happy path

Evidence:
- raw JSON-RPC `initialize` returned the MCP handshake successfully
- raw JSON-RPC `tools/call` to
  `prepare_session_distill(project_name="v2957-empty-packet", run_ingest=false, observation_limit=5, max_chars_per_observation=2000)`
  returned success
- returned packet fields were:
  - `ingest.reason = "run_ingest=false"`
  - `status.observation_count = 0`
  - `status.memory_entry_count = 0`
  - `status.task_handoff_count = 0`
  - `status.confirmed_rule_count = 0`
  - `status.pending_candidate_count = 0`
  - `observation_count = 0`
  - `observations = []`

Boundary:
- 这条 entry 证明 **generic MCP 的空 evidence packet 场景** 现在已经有 real stdio evidence，
  而不只是 packet 表里的预期描述。
- 它仍**不等于**用户可见 agent 总结文案已经在每个 client 上都收成 “no recent session evidence”；
  这里验证的是底层 `prepare_session_distill` 空包返回。
- 它也**不等于** full matrix 已完成：S4 / S5 / S7 / S10 / S11 / S12 仍未在 generic MCP 上补齐。

## 2026-06-04 — Generic MCP cross-session confirmed truth visibility (Windows, isolated temp home)

Clients: Generic MCP client (writer session + reader session, raw JSON-RPC over stdio contract)
harness-mem version: 2.9.58
Project: `v2958-cross-session`
Environment: isolated temp home, two independent MCP server processes, `HARNESS_MEM_DISABLE_EMBEDDINGS=1`

Pass: near-neighbor S10 (confirmed truth written in one MCP session and surfaced by `wake` in a second MCP session)
Not run: full 12-scenario matrix, UI-level Codex/Claude/Cursor cross-client pair, S4/S5/S7/S11/S12

Evidence:
- writer session `initialize` returned the MCP handshake successfully
- reader session `initialize` returned the MCP handshake successfully
- writer session `set_active_project(project_name="v2958-cross-session")` returned success
- writer session `suggest_memory_entry(...)` returned pending entry id `09775849-a946-4d38-87a5-aab036a2f19b`
- writer session `confirm_memory_entry(entry_id=...)` returned `status = "accepted"`
- reader session `wake(project_name="v2958-cross-session", no_auto_ingest=true)` returned success
- returned wake output included the confirmed truth under `# Essential Truth (L1 · confirmed current)`:
  `Cross-session confirmed truth should surface in wake output.`

Boundary:
- 这条 entry 证明 **两个独立 generic MCP 会话** 之间已经有 live confirmed-truth visibility：
  writer 会话确认的事实，reader 会话随后 `wake` 能读回。
- 它仍**不等于** packet 表里更强的 UI 级 cross-client pair 已完成；当前还没有
  Codex→Claude、Cursor→Claude 或 integration-workspace Cursor pair 的对应 run log。
- 它也**不等于** full matrix 已完成：这里只把 generic MCP 从单会话 smoke 再推进到了跨会话 truth visibility。

## 2026-06-04 — Wake renderer confirmed-truth readback (Windows, isolated temp home)

Clients: repo-owned wake renderer read path (`cmd_wake_up`), not a client transcript
harness-mem version: 2.9.60
Project: `v2961-wake-renderer-truth`
Environment: isolated temp home, confirmed current-truth entry already stored

Pass: near-neighbor S10 read-side evidence (accepted truth is rendered back through the real wake command)
Not run: Codex→Claude / Cursor→Claude UI pair, client transcript, write-side natural-language flow

Evidence:
- temp backend stored one accepted current-truth `MemoryEntry`
- `cmd_wake_up(project_name="v2961-wake-renderer-truth", no_auto_ingest=true)` returned success
- rendered output included `# Essential Truth  (L1 · confirmed current)`
- rendered output included:
  `Wake renderer should surface confirmed truth written earlier.`

Boundary:
- 这条 entry 证明 **repo 自己的真实 wake 读端** 已经会把已确认事实渲染回 L1，
  所以 S10 不再只有 raw MCP `wake(...)` 的 payload 近邻证据。
- 它仍**不等于** packet 单元格要求的 UI 级 cross-client pair：这里没有 Codex 写端 +
  Claude/Cursor 读端的真实 transcript，只是把读端推进到了真正的 `cmd_wake_up` renderer。
- 它也**不等于** Cursor integration 工作区上的 packet run log 已存在。

## 2026-06-04 — Generic MCP distill summary stays repair-only (Windows, isolated temp home)

Clients: Generic MCP client (raw JSON-RPC over stdio contract)
harness-mem version: 2.9.59
Project: `v2959-review-only`
Environment: isolated temp home, `HARNESS_MEM_DISABLE_EMBEDDINGS=1`

Pass: near-neighbor S12 (successful auto-review summary does not tell the user to run `/hm:review`)
Not run: full natural-language distill happy path, UI-level slash/client summary wording, S4/S5/S7/S11

Evidence:
- raw JSON-RPC `initialize` returned the MCP handshake successfully
- raw JSON-RPC `set_active_project(project_name="v2959-review-only")` returned success
- two pending entries were created via `suggest_memory_entry(...)`
- `auto_review_candidates(project_name="v2959-review-only", apply=true)` returned success with:
  - `new_candidates = 2`
  - `auto_rejected = 1`
  - `kept_pending = 1`
  - `needs_user_confirmation = 1`
  - `next_user_action = "review the deferred candidates and mention any incorrect item id"`
- returned summary payload did **not** contain `/hm:review`

Boundary:
- 这条 entry 证明 **generic MCP 的成功 auto-review summary** 已经保持 repair-only 边界：
  它不会在成功收口后默认把用户推去跑 `/hm:review`。
- 它仍**不等于**所有 client 的自然语言 distill 摘要都已经逐字验证；这里验证的是 generic MCP
  summary payload，而不是 Codex / Cursor / Claude 的最终 UI 表述。
- 它也**不等于** packet 全补齐：这里只推进了 S12 的 generic MCP 证据。

## 2026-06-04 — Stale CLI surface scan (repo truth, packet S11)

Clients: Repo truth / string scan (shared across Claude Code, Codex CLI, Cursor, generic MCP docs surface)
harness-mem version: 2.9.60
Working tree scope: packet-defined S11 scan targets only

Pass: S11 (stale daily CLI surface absent in the packet-defined user-doc range)
Not run: client UI execution; this is the packet's explicit string-scan scenario

Scan command:

```text
rg "harness-mem (wake|search|timeline|candidates|distill)\b" README.md AGENTS.md plugins/harness-mem/README.md plugins/harness-mem/commands/hm/*.md tools/session-distill/SKILL.md
```

Observed hits:
- `AGENTS.md`: `harness-mem distill` only appears inside a sentence that says the CLI subcommand was removed in v2.0
- `tools/session-distill/SKILL.md`: `harness-mem ingest` / `harness-mem distill` only appear inside a sentence that says ordinary users are **not required** to run them manually
- no hit in `README.md`
- no hit in `plugins/harness-mem/README.md`
- no hit in `plugins/harness-mem/commands/hm/*.md`
- no hit that teaches `harness-mem wake/search/timeline/candidates/distill` as the current daily user path

Boundary:
- 这条 entry 证明 **packet 定义范围内的 stale daily CLI surface** 现在已经只剩反例说明或删除说明，
  不再作为当前用户 workflow 教学出现。
- 它仍**不等于**整个仓库所有历史文档都绝对零命中；这里只验证 packet S11 明确定义的扫描范围。

## 2026-06-04 — Generic MCP transport unavailable repro (Windows, isolated broken launch command)

Clients: Generic MCP client (raw subprocess/stdin/stdout repro, not a full IDE transcript)
harness-mem version: 2.9.60
Project: n/a
Environment: current machine, intentionally broken MCP launch command

Pass: lower-layer S4 evidence (MCP server process cannot be reached when the launch target is invalid)
Not run: Codex / Cursor / Claude client-facing error wording, doctor pointer wording, stale-CLI fallback wording

Repro command shape:

```text
python -m harness_mem.mcp.server_missing
```

Observed result:

- subprocess exited before any JSON-RPC handshake
- return code: `1`
- stdout: empty
- stderr:
  `C:\Users\ManHua\.local\python313\python.exe: No module named harness_mem.mcp.server_missing`

Boundary:
- 这条 entry 证明 **当前机器上已经能真实复现一种 S4 根因**：client 指向了错误的 MCP 启动目标时，
  server 进程会在握手前失败，transport 实际不可达。
- 它仍**不等于** packet 单元格要求的完整 client-facing 行为：这里还没有看到 Codex / Cursor /
  Claude 在 UI 中如何把这类失败翻译成“harness-mem MCP runtime unavailable”并指向
  `harness-mem doctor`。
- 它也**不等于**旧 daily CLI fallback 已在真实 client transcript 里被逐字排除；这条只补了
  S4 的底层 runtime repro，不是最终用户表述验证。

## 2026-06-03 — Cursor hook install smoke (Windows, temp project)

Clients: Cursor integration asset only (not a full Cursor agent run)
harness-mem version: 2.9.55
Project: temp `hm-cursor-hook-smoke`

Pass: installation asset generation for Cursor after-agent hook
Not run: Cursor agent conversation / MCP tool invocation / packet scenarios

Evidence:
- `python -m harness_mem.cli integration install-cursor-hook --project-root <temp>` returned success
- generated file path: `C:\Users\ManHua\AppData\Local\Temp\hm-cursor-hook-smoke\.cursor\hooks\after-agent.sh`
- generated hook embeds shipped `python -m harness_mem.host_entry --project-root ... --source ide_hook` invocation

Boundary:
- 这条 entry 只证明 **Cursor 接入资产** 在当前机器上可生成，且生成内容符合 shipped host-entry contract。
- 它**不是** Cursor agent run log，不证明 Cursor 已经跑通 `wake` / `distill` / `search` 场景。

## 2026-06-03 — Cursor runtime stack evidence (Windows, local Cursor logs + project MCP cache)

Clients: Cursor runtime stack evidence only (not a full Cursor agent memory run)
harness-mem version: 2.9.55
Project: `f:\memory-lab\harness-mem\harness_mem\integration`

Pass: Cursor workspace observed with hooks runtime, agent exec startup, MCP router connection, and harness-mem tool discovery cache
Not run: Cursor agent memory workflow scenarios

Evidence:
- local Cursor log file:
  `C:\Users\ManHua\AppData\Roaming\Cursor\logs\20260601T022248\window6\output_20260603T201000\cursor.hooks.workspaceId-2b592b96a83127a0fa3ca09b800709f8.log`
- local Cursor agent log file:
  `C:\Users\ManHua\AppData\Roaming\Cursor\logs\20260601T022248\window6\exthost\anysphere.cursor-agent-exec\Cursor Agent Exec.log`
- local Cursor MCP log file:
  `C:\Users\ManHua\AppData\Roaming\Cursor\logs\20260601T022248\window6\mcp-server-user-mcp-router.workbench.log`
- local Cursor project MCP cache:
  `C:\Users\ManHua\.cursor\projects\f-memory-lab-harness-mem-harness-mem-integration\mcps\user-mcp-router\tools\`
- that log mentions:
  - `Project config path (integration): f:\memory-lab\harness-mem\harness_mem\integration\.cursor\hooks.json`
  - `Claude project config path (integration): f:\memory-lab\harness-mem\harness_mem\integration\.claude\settings.json`
  - `Claude project local config path (integration): f:\memory-lab\harness-mem\harness_mem\integration\.claude\settings.local.json`
  - `cursor_agent_exec.startup.workspace_paths {"workspacePathCount":1,"workspacePaths":["f:\\memory-lab\\harness-mem\\harness_mem\\integration"]}`
  - `createClient completed for server: user-mcp-router, connected=true, statusType=connected`
  - MCP cache files exist for harness-mem tools including `wake.json`, `set_active_project.json`, and `suggest_memory_entry.json`

Boundary:
- 这条 entry 证明 **Cursor runtime stack** 在当前机器上已经看到了 harness-mem integration 工作区：
  hooks service 初始化了该工作区，agent exec 在该工作区启动，`mcp-router` 在该窗口连通，且项目级 MCP cache 已落出 harness-mem 工具描述。
- 它仍**不是** Cursor agent memory run log：没有直接证据表明 Cursor agent 已实际调用 `wake`、`prepare_session_distill`、
  `suggest_memory_entry` 或其它 harness-mem MCP tools。

## 2026-06-03 — Cursor agent run-log evidence (Windows, local Cursor project transcripts)

Clients: Cursor agent transcript evidence (real MCP calls, but not the `integration` workspace packet run)
harness-mem version: 2.9.55
Project: `f:\huiben\bazi-apps`

Pass: real Cursor agent MCP usage observed for search/timeline/status-adjacent harness-mem flows
Not run: `integration` workspace packet scenarios, full 12-scenario matrix

Evidence:
- local Cursor project transcript:
  `C:\Users\ManHua\.cursor\projects\f-huiben-bazi-apps\agent-tools\e0584dd0-f277-4a9d-8298-3f2de91906c1.txt`
- local Cursor project transcript:
  `C:\Users\ManHua\.cursor\projects\f-huiben-bazi-apps\agent-tools\cb589791-18c0-473a-afc0-ef6d583288d8.txt`
- those transcripts show real Cursor agent tool calls including:
  - `mcp__harness-mem__search_memory`
  - `mcp__harness-mem__timeline`
  - `mcp__harness-mem__get_project_profile`
  - `mcp__harness-mem__get_task_handoffs`
  - `mcp__harness-mem__get_confirmed_rules`
- one transcript also shows a concrete natural-language flow:
  - user asks Cursor to use `search_memory` for `bazi-apps`
  - Cursor agent responds with the empty result and records `Tools: mcp__harness-mem__search_memory`
  - user then asks for `timeline`
  - Cursor agent responds and records `Tools: mcp__harness-mem__timeline`
  - later `/hm:status`
  - Cursor agent diagnoses via `mcp__harness-mem__get_project_profile`, `mcp__harness-mem__get_task_handoffs`, and `mcp__harness-mem__get_confirmed_rules`

Boundary:
- 这条 entry 证明 **当前机器上已经存在真实的 Cursor agent run log**，而且不是只停留在工具发现或 hooks/runtime stack 层。
- 它仍**不等于** v2.2 packet 已经在 Cursor 上补齐：这些 run log 来自 `bazi-apps` 项目，不是
  `harness_mem/integration` 工作区，也还没有覆盖 packet 定义的 full 12-scenario matrix。
- 当前明确仍缺的强证据有四类：
  - UI 级 `S10` cross-client pair（如 Codex→Claude、Cursor→Claude）
  - full matrix 里尚未补齐的 `S4 / S5 / S7 / S11`
  - `harness_mem/integration` 工作区上的真实 Cursor packet scenario run log
  - 能直接对应 packet 单元格的 client-facing transcript，而不只是 runtime / cache / transcript 旁证
