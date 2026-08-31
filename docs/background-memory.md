# 后台记忆说明

> 给开发者看的短说明：Hook 之后怎么自动整理会话、要配什么、回执里看什么。

---

## 30 秒版

1. **开后台**：项目里 `distill.autonomous.enabled=true`
2. **用哪个 CLI**：看当前宿主（Hook 的 `host_client` / `HARNESS_MEM_CLIENT`）— 跟宿主走对应 CLI，不是 harness-mem 里再选一次。已接后台 CLI 的宿主包括 Codex、Hermes、Claude Code、OpenCode（回执为 `codex_cli`、`hermes_cli`、`claude-code_cli`、`opencode_cli`）；其它宿主仍按同一规则，由 Hook 传入的 client 决定
3. **传输 / 密钥 / Sub2API**：配在**该宿主 CLI** 自己的配置里，不是 harness-mem 项目配置
4. **关后台**：`distill.autonomous.enabled=false`

**不需要** `semantic.execution.profile`，**不需要**在 `~/.harness-mem/config.toml` 里登记 provider。旧键在加载时会被忽略。

---

## 配置示例

**项目**（`.harness-mem.toml` 或 `harness-mem config set`）：

```toml
[distill.autonomous]
enabled = true
```

```bash
harness-mem config set distill.autonomous.enabled true --scope project --confirm
```

`semantic.execution.profile` 与 `[semantic.providers.*]` 为**已删除路径**；配置加载时会剥离，不参与后台授权或执行。

---

## 后台会做什么

```text
Stop Hook → 保存会话 → Dream/worker → 当前宿主 CLI → 本机验证 → 写 Note / SQLite
```

- **Hook 蒸馏**：整理刚结束的会话  
- **Dream 复核**：对照已有知识和来源（同一宿主 CLI）  
- **人工 distill**：仍在当前 IDE/Agent 里做

---

## 回执（receipt）看什么

成功的一次后台运行：

```json
"execution_mode": "agent",
"provider": { "name": "hermes_cli", "host_client": "hermes" }
```

| 字段 | 成功时 |
|------|--------|
| `execution_mode` | `agent` |
| `provider.name` | `{host}_cli`（如 `codex_cli`、`hermes_cli`、`claude-code_cli`、`opencode_cli`） |
| `hook_reentry_count` | `0` |

---

## status / Doctor

`health_card.authorization`：

| 字段 | 含义 |
|------|------|
| `ready` | 能跑后台（`enabled=true` 且未被 legacy restricted 关掉） |
| `on` | 同左 |
| `reason` | `ok` / `disabled` / `legacy_restricted_off` |
| `message` | 短英文说明 |

---

## 代码里（读源码时）

| 短名 | 含义 |
|------|------|
| `background_on(config)` | 开关算「开」 |
| `background_ready(config)` | 能跑后台 CLI（目前 = `background_on`） |
| `background_status(config)` | 上面 + `reason` |

---

## 相关文件

| 主题 | 路径 |
|------|------|
| 授权 | `harness_mem/autonomous/authorization.py` |
| CLI 执行 | `harness_mem/autonomous/executors/` |
| Worker | `harness_mem/autonomous/worker.py` |
| Dream | `harness_mem/commands/dream.py` |
