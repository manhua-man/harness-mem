# Roadmap: harness-mem v2.3 - v2.4

> 状态：规划中。本文把 v2.2 之后的“记忆进化”工作拆成两个版本。
>
> v2.3 把旧的 v1.9 Memory Metabolism / Dream 远景落成 candidate-first 的实现计划；旧 v1.9 vision 文档不再单独保留。v2.4 做跨项目 procedural Skill 复用和可控 Skill 激活，但不把 harness-mem 变成 always-on assistant runtime。

---

## 共同原则

v2.3 / v2.4 都遵守这些边界：

- **Candidate before truth**：merge、supersede、skill 改进、memory 抽象都先进 candidate / suggestion 层。
- **Raw evidence first**：任何新结构都必须能回链到 observation、session、review outcome 或 retrieval signal。
- **No always-on daemon**：周期性工作可以由用户、Agent、外部 scheduler 或宿主 IDE 触发，但 harness-mem 不拥有常驻 assistant lifecycle。
- **Main task 不被记忆系统绑架**：代谢和 skill sharing 失败时应降级为“稍后建议/可重试”，不能阻断当前开发任务。
- **不做 AI 自治删 truth**：旧 truth 可以通过可审核 supersede 流程变成历史，但不能静默删除。

---

## v2.3：Memory Metabolism Foundations

**主题**：让记忆库能 replay、压缩、弱化、强化、生成结构建议；所有影响 truth 的变化仍然需要审核。

### v2.3.0：Signals and Replay Windows

**用户故事**：系统能解释为什么这批旧记忆被选中整理，而不是黑箱扫全库。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | 新增 `DreamRun` / `MetabolismRun` 记录 | 保存 run id、project、input window、selected signals、output counts、耗时、状态 |
| P0 | 记录 retrieval / review signal | confirm/reject、wake surfaced、search hit、skill result、supersede outcome 进入结构化信号层 |
| P0 | Replay window selector | 能从近期 observation、stale pending candidate、historical truth、低成功率 skill、重复 search hit 中选取整理窗口 |
| P1 | preview-only run | Agent 可运行代谢 preview，只展示输入窗口，不写 suggestion |
| P1 | 预算护栏 | replay window 按 count/token/type 有硬上限，旧 observation 不能淹没当前任务 |

### v2.3.1：Compression and Stale Suggestions

**用户故事**：系统能发现疑似重复或过期记忆，但必须先给出 reviewable suggestion。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `MergeSuggestion` candidate | 对重复 candidate/fact 生成合并建议，每个来源都有 provenance |
| P0 | stale / supersede suggestion | 当旧 truth 与新 confirmed truth 或 observed workflow 冲突时，生成可审核建议 |
| P0 | weak-link signal | 对低命中、低置信、过期连接打弱化信号，但不删除源记录 |
| P1 | review surface | `/hm:review` 能把 metabolism suggestions 和普通 memory candidates 分开展示 |
| P1 | safety tests | 测试证明 preview 和 suggestion generation 不会 mutate confirmed truth |

### v2.3.2：Structure Synthesis

**用户故事**：重复的排障流程和项目约定不只是被摘要，而是能变成更好的结构化候选。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | procedural improvement suggestion | 低成功率或重复出现的 Skill pattern 能生成新的 `ProceduralCandidate` revision |
| P0 | relation cluster suggestion | 重复 entity/relation 共现可以生成带 evidence 的 relation cluster candidate |
| P1 | candidate quality metrics | 按 suggestion type 记录 confirm/reject/defer rate |
| P1 | rollback story | 每条确认后的 metabolism suggestion 都有 provenance，后续可 supersede 或 reject |

### v2.3 Non-Goals

- 不做跨项目 Skill library
- 不做后台 daemon
- 不自动 mutate confirmed truth
- 不把 procedural skill 默认注入 wake
- 没有指标就不宣称“Dream 让系统变好了”

---

## v2.4：Cross-Project Skills and Controlled Activation

**主题**：让有价值的 procedural knowledge 可以跨项目复用，但必须显式、带上下文边界、可审核。

### v2.4.0：Cross-Project Skill Library

**用户故事**：一个 repo 学到的 release hygiene skill 可以被另一个 repo 借用，但不会把项目特定细节乱套过去。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | Skill scope model | Skill 增加 `scope = project | workspace | global`、origin project、portability notes |
| P0 | promotion candidate | project skill 只能通过 reviewable candidate 提升为跨项目 skill |
| P0 | context guard | 跨项目 skill 带 applicability constraints 和 forbidden assumptions |
| P1 | cross-project search | `search_skills` 只有在 Agent workflow 显式请求时才包含 shared skills |
| P1 | provenance display | shared skill 输出 origin project 和 evidence，Agent 使用前可解释来源 |

### v2.4.1：Skill Activation Hints

**用户故事**：任务开始时，Agent 可以知道“可能有一个有用 Skill”，但不会把完整步骤塞进每次 wake。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | wake skill hints，而不是默认注入完整 skill body | wake 可在独立预算里给 compact skill id/title/reason；完整步骤必须显式 `search_skills` |
| P0 | opt-in activation | skill hints 由 config / tool parameter / agent command 控制，不做静默行为变化 |
| P1 | conflict handling | project-specific skill 与 shared skill 冲突时，默认 project-specific 胜出 |
| P1 | usage feedback | `record_skill_result` 记录 hinted skill 是否被使用、是否有帮助 |

### v2.4.2：Host-Triggered Reflection, Not Daemon

**用户故事**：客户端可以提供一个 end-of-task “reflect and suggest memory”动作，但 harness-mem 自己不跑后台 agent。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | explicit reflection command contract | 定义用户/宿主触发的 reflection 流程：任务后提出候选，而不是自动写 truth |
| P0 | no implicit turn-end writes | 测试和文档断言：没有用户/宿主/Agent workflow 触发，就不会产生候选 |
| P1 | host integration guidance | 文档说明 IDE 或外部 scheduler 如何安全触发 reflection |
| P1 | interruption safety | reflection 失败不阻断主任务，只输出可恢复诊断 |

### v2.4 Non-Goals

- 不做 always-on daemon
- 不默认启用 IDE hook
- 不做无审核自学习进 confirmed truth
- 不做无审核跨项目 Skill promotion
- 不显式请求时，不把完整 skill body 放进默认 wake

---

## 旧“未做项”的归宿

| 未做项 | 放置 |
|---|---|
| v1.9 Memory Metabolism / Dream | v2.3，重命名为 candidate-first Memory Metabolism foundations |
| 跨项目 Skill sharing | v2.4.0 |
| 后台 daemon / IDE hook / turn-end 自检 | v2.4.2 只做显式 host-triggered reflection；daemon 仍是 non-goal |
| procedural skill 默认进入 wake | v2.4.1 只做 compact opt-in hints；完整默认注入仍是 non-goal |
| 自动删除 / AI 自治改 truth | 永不做；只走 supersede / candidate / review |
