# 后台记忆说明

> 给开发者看的短说明：Hook 之后怎么自动整理会话、要配什么、回执里看什么。

---

## 30 秒版

1. **开后台**：项目里 `distill.autonomous.enabled=true`
2. **用哪个 CLI**：默认跟当前宿主；项目也可以明确选择 Codex、Hermes、Claude Code 或 OpenCode。Cursor、Grok、Antigravity 等没有同名后台 CLI 的宿主必须明确选择，不能偷偷改成 Codex
3. **传输 / 密钥 / Sub2API**：配在**所选 CLI** 自己的配置里，不是 harness-mem 项目配置
4. **关后台**：`distill.autonomous.enabled=false`

**不需要** `semantic.execution.profile`，**不需要**在 `~/.harness-mem/config.toml` 里登记 provider。旧键在加载时会被忽略。

---

## 配置示例

**项目**（`.harness-mem.toml` 或 `harness-mem config set`）：

```toml
[distill.autonomous]
enabled = true
cli = "current" # 或 codex / claude-code / hermes / opencode
```

```bash
harness-mem config set distill.autonomous.enabled true --scope project --confirm
harness-mem config set distill.autonomous.cli hermes --scope project --confirm
```

`semantic.execution.profile` 与 `[semantic.providers.*]` 为**已删除路径**；配置加载时会剥离，不参与后台授权或执行。

---

## 后台会做什么

```text
Stop Hook → 保存会话 → Dream/worker → 所选 CLI → 本机验证 → 写 Note / SQLite
```

- **Hook 蒸馏**：整理刚结束的会话  
- **Dream 复核**：对照已有知识和来源（同一个所选 CLI）
- **人工 distill**：仍在当前 IDE/Agent 里做

---

## 回执（receipt）看什么

成功的一次后台运行：

```json
"provider": { "name": "hermes_cli", "host_client": "hermes" }
```

| 字段 | 成功时 |
|------|--------|
| `provider.name` | `{host}_cli`（如 `codex_cli`、`hermes_cli`、`claude-code_cli`、`opencode_cli`） |
| `hook_guard_check.all_blocked` | `true` |
| `hook_guard_check.downstream_jobs_created` | `0` |

后台调用的是所选 CLI Agent；harness-mem 不改写该 CLI 的模型、服务地址、账号、
密钥或规则。任务所需来源已经完整放进输入，所以调用不加载无关工具；它还会阻止
后台 Agent 重新进入 harness-mem Hook，并在本机校验返回 JSON。

---

## status / Doctor

`health_card.authorization`：

| 字段 | 含义 |
|------|------|
| `ready` | 后台已开，而且所选 CLI 可用 |
| `on` | 后台开关已开 |
| `selected_cli` | 实际准备调用的 CLI |
| `reason` | `ok` / `disabled` / `host_not_detected` / `unsupported_cli` / `cli_not_found` |
| `message` | 短英文说明 |

---

## 代码里（读源码时）

| 短名 | 含义 |
|------|------|
| `background_on(config)` | 开关算「开」 |
| `background_status(config)` | 上面 + `reason` |

---

## 相关文件

| 主题 | 路径 |
|------|------|
| 发版 Hook 验收 | `docs/hook-release-checklist.md` |
| 授权 | `harness_mem/autonomous/authorization.py` |
| CLI 执行 | `harness_mem/autonomous/executors/` |
| Worker | `harness_mem/autonomous/worker.py` |
| Dream | `harness_mem/commands/dream.py` |
