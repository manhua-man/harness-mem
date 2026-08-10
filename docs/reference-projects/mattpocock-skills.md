# mattpocock/skills

- 定位：面向编码 Agent 的组合式工作流 Skill 集；不是 memory store 或
  harness-mem runtime 依赖。
- 上游：<https://github.com/mattpocock/skills>。
- 本地研究镜像：
  `F:\AIInfra\upstreams\harness-mem\mattpocock-skills`。
- 复核基线：`main` 的 `2ab958093e83e0ec752e6c1c5932da465bf23e0c`
  （2026-08-02）。最新稳定 tag 为 `v1.1.0`；`package.json` 为 `1.1.0`，
  `.claude-plugin/plugin.json` 声明 `1.2.0`，因此升级必须按 commit 和源码
  能力核验，不能只抄一个版本字符串。
- 许可证：MIT；复制或实质性移植必须保留版权和许可声明。

## 架构与组合方式

```text
user-invoked wrapper
  -> model-invoked workflow skill
  -> shared vocabulary / domain discipline
  -> repo facts + user decisions
  -> issue/docs/code artifact
```

许多入口 Skill 极薄，只负责组合其他 Skill。上游确实包含 `grill-me`，其当前
实现只负责显式启动 `grilling`；`grill-with-docs` 则把 `grilling` 与
`domain-modeling` 组合起来。完整行为来自依赖闭包，而不是两个入口文件本身：

- `grill-me`：用户显式入口，声明 relentless interview，然后委托 `grilling`。
- `grilling`：沿决策树一次只问一个问题；每问都给推荐答案；事实由 Agent 查，
  决策交给用户；达成共同理解前不执行。
- `domain-modeling`：维护 canonical terminology，用边界场景和代码反证模糊术语；
  只在“难逆转、缺上下文会意外、存在真实权衡”同时成立时写 ADR。
- `agents/openai.yaml`：将 `grill-with-docs` 设为显式调用，避免模型在普通任务中
  自动启动长访谈。

这套设计的优势是组合面很小、职责清晰；风险是只复制 wrapper 会得到一个缺失
依赖的空壳，而且它的文档写入语义不能直接接入无人值守 memory distill。

## 可复核证据

| 主题 | 本地源码证据 | 结论 |
|---|---|---|
| grill-me 入口 | `skills/productivity/grill-me/SKILL.md` | 显式入口，实际委托 grilling。 |
| 组合入口 | `skills/engineering/grill-with-docs/SKILL.md` | 组合 grilling 与 domain-modeling。 |
| 访谈纪律 | `skills/productivity/grilling/SKILL.md` | 一次一问、提供推荐、事实先查、未确认不执行。 |
| 领域模型 | `skills/engineering/domain-modeling/SKILL.md` | glossary、代码反证、边界场景和严格 ADR 条件。 |
| 调用策略 | `skills/engineering/grill-with-docs/agents/openai.yaml` | 只允许用户显式调用。 |
| 版本与许可 | `package.json`、`.claude-plugin/plugin.json`、`LICENSE` | 版本元数据不一致；许可证为 MIT。 |

## 对 harness-mem：adopt / adapt / reject

**Adopt**：提供显式可选的 `grill-with-docs` Skill，用于产品、架构、schema、
policy 和领域术语讨论。事实先查，用户决策一次一问，确认后才更新 glossary/ADR。

**Adapt**：

- 将 code-review 的双轴思想用于零候选：Evidence fidelity 与 Future utility
  分开记录，不用一个模糊总分吞掉漏判。
- 将 triage 的 collect → verify → challenge → terminal state 顺序用于
  `no_candidate` runtime gate。
- 将 research 的 primary-source 原则用于外部事实验证，但不引入其后台文件写入
  实现。
- 将 diagnosing-bugs 的 replay-first 方法用于误晋升和漏候选评测。

**Reject**：用交互访谈替换 `hm-distill` 的内联候选准入；将访谈放进 wake/backlog；引入
上游 issue tracker、handoff、implement 或 wayfinder 整条产品面；让未确认讨论
自动写入项目文档或长期记忆。

## 复查触发

- 上游发布新稳定 tag，或 `grilling`、`domain-modeling`、调用策略发生变化。
- harness-mem 需要扩展产品/架构决策捕获或领域术语治理。
- 当前 pinned commit 出现安全、许可或兼容性问题。
