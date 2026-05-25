# Roadmap: harness-mem v2.4

> 状态：规划中。
>
> 主题：Host-triggered Reflection + Queue Health。吸收 `claude-mem` 的运行时韧性，但不照搬 daemon / hook 绑定。

---

## 目标

v2.4 让 reflection、distill、metabolism 这类较重任务有清晰的 job 生命周期和健康检查。

这一版不追求“自动随手记”，而是定义安全的 host-triggered reflection：由用户、Agent workflow、IDE command 或外部 scheduler 显式触发，失败时可见、可诊断、可重试。

---

## 技术来源

- `claude-mem`：CLAIM-CONFIRM queue、worker health、graceful degradation。
- harness-mem v2.3：`RetrievalSignal` 和 `MetabolismRun` 提供 replay / health 输入。
- harness-mem 既有边界：候选先进 review，不允许静默写 confirmed truth。

---

## Scope

| 领域 | v2.4 决策 |
|---|---|
| Reflection | 只允许显式触发 |
| Queue | 引入 job lifecycle，不引入默认常驻 worker |
| Health | doctor 能看见 stuck / failed / stale 状态 |
| Truth | reflection 只能写 candidate / suggestion |
| 主任务 | 记忆任务失败不阻断当前 coding task |

---

## v2.4.0：Reflection Job Model

**用户故事**：我触发一次任务后反思，它要么完成，要么可重试，不能无声卡住。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `ReflectionJob` / `ReviewJob` schema | job 有 `pending / processing / completed / failed / retryable` 状态 |
| P0 | processing lease | processing 超时后可恢复为 retryable |
| P0 | job provenance | 每个 job 记录触发来源、project、input window、输出 candidate ids |
| P1 | retry policy | retry 不重复写相同 candidate |
| P1 | job list/read MCP helper | Agent 能查看最近 job 和失败原因 |

## v2.4.1：Host-Triggered Reflection Contract

**用户故事**：客户端可以在任务后显式触发“整理一下”，但 harness-mem 自己不偷偷监听每个 turn。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | reflection contract | 定义 user / Agent / IDE / scheduler 四类触发来源 |
| P0 | no implicit writes tests | 没有显式触发时，不产生 candidate / reflection job |
| P0 | output shape | 输出候选数量、auto-review 结果、失败诊断、下一步 |
| P1 | interruption safety | 任务中断后 job 可恢复或明确失败 |

## v2.4.2：Queue Health and Doctor

**用户故事**：记忆系统出问题时，我能知道是队列卡住、信号没写、候选过期，还是索引坏了。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | doctor queue checks | 报告 pending / processing / failed / retryable counts |
| P0 | stale candidate checks | 报告长期 pending 和高风险未处理项 |
| P0 | signal freshness checks | 报告最近 signal write 和 chronic failures |
| P1 | index / WAL size hints | 大库给出 maintenance 建议 |
| P1 | health payload for MCP | Agent 能拿结构化 health summary |

---

## Non-Goals

- 不做 always-on daemon。
- 不默认启用 IDE hook。
- 不静默写 confirmed truth。
- 不把 File Read Gate 做成阻断行为。
- 不做 cross-project skill。

---

## 后续归宿

| 能力 | 后续版本 |
|---|---|
| context assembly / Memory Stack renderer | `docs/roadmap-v25.md` |
| wiki bridge / compact index / contradiction suggestions | `docs/roadmap-v26.md` |
| cross-project skill / controlled activation | `docs/roadmap-v27.md` |

