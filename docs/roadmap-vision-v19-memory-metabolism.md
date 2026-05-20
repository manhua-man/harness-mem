# harness-mem v1.9 远景：Dream 不是自动记忆，而是 Memory Metabolism

> 状态：远景文档（vision），不是承诺路线图。
>
> 本文档配合 [`roadmap-vision-v16-v18.md`](./roadmap-vision-v16-v18.md) 阅读：`v1.6 - v1.8` 解决的是“记忆系统的器官怎么长出来”，`v1.9` 讨论的是“这些器官如何形成一个真正会代谢、会重组、会自进化的系统”。

---

## 为什么单独写 v1.9

到了 `v1.8` 结束时，本仓理论上已经具备三类关键部件：

- `v1.6` 的 **持久化向量、记忆分型、分桶预算、只读 distill 边界**
- `v1.7` 的 **时间维度、supersede、history-preserving truth update**
- `v1.8` 的 **procedural memory / skill schema / skill candidate 闭环**

这三步做完以后，系统就不再只是“能存、能查、能确认”，而是第一次具备做 Dream 的前提。

所以 `v1.9` 不是“再加一个自动摘要命令”，也不是“让记忆库自己多写点东西”，而是：

> 让 `harness-mem` 从“带审核的知识库存储层”
> 进化为“带代谢能力的记忆系统”。

---

## 核心命题

这份文档的中心观点只有一句话：

> **Dream 不是自动记忆，而是 Memory Metabolism。**

这里的 “metabolism” 指的不是 poetic metaphor，而是一个可工程化的系统能力：

- 会重放近期经验
- 会压缩与重组已有记忆
- 会强化高价值连接
- 会弱化低价值连接
- 会生成新的抽象单元
- 会在不破坏审计链的前提下持续调整自身结构

换句话说，知识库的核心不该只是“越攒越多”，而应该是“越用越会整理自己”。

---

## 从人脑类比到系统映射

人脑的类比是有帮助的，但必须落成系统对象，不能停在比喻层。

| 人脑类比 | 在 `harness-mem` 里的工程映射 |
|---------|------------------------------|
| 睡眠 replay | 对近期 observation / task handoff / retrieval hit / review outcome 做离线重放 |
| 突触增强 | 被高频命中、高频确认、高频共现的记忆节点与关系边得到权重提升 |
| 突触修剪 | 低命中、低价值、被 supersede 的连接被降权、归档、移出 wake 默认注入 |
| 新生神经元 | 形成新的 rule candidate、relation cluster、skill candidate、memory subtype |
| 海马体到皮层迁移 | episodic observation 逐步沉淀为 semantic fact / procedural skill |
| 梦中重组 | 把原本分散的 session 片段重连为更高层的结构：流程、模式、因果链 |

这里最重要的不是“像不像人脑”，而是：

- **系统是否有重放机制**
- **系统是否有连接强度变化**
- **系统是否有结构生成能力**
- **系统是否有可控遗忘**

如果只有“新内容不断 append”，那不叫代谢，只叫堆积。

---

## v1.9 的设计目标

`v1.9` 不再把 Dream 看作一个孤立命令，而是一个跨层循环。

它的目标不是“自动多记”，而是同时做到这四件事：

1. **压缩**
   把原始 session 里的冗余 observation 去重、聚类、摘要，减少 wake 注入噪声。

2. **强化**
   把真正反复出现、反复命中、反复确认的知识提升成更稳定的 semantic / procedural memory。

3. **弱化**
   把低价值、低复用、长期无命中的连接降权，而不是默认永远和高价值记忆同权存在。

4. **生成新结构**
   不只是更新内容，而是长出新的节点和边，例如：
   - 新的 relation cluster
   - 新的 skill candidate
   - 新的 failure pattern
   - 新的 project-specific memory subtype

---

## v1.9 与 v1.6 - v1.8 的关系

`v1.9` 不是独立飞出来的第四条路线，而是前面三步的上层合成。

### v1.6 提供的前提

- 有了分型，Dream 才能按 `episodic / semantic / procedural` 做不同代谢策略
- 有了预算纪律，Dream 才能决定什么该保留在热上下文，什么该退到冷层
- 有了只读 distill 边界，Dream 才不会演化成“能直接改真值”的黑箱

### v1.7 提供的前提

- 有了 `valid_from / valid_to / recorded_at`，Dream 才能区分“当前有效”和“历史曾真”
- 有了 supersede，Dream 才能安全地做“弱化旧连接”而不是粗暴删记忆

### v1.8 提供的前提

- 有了 skill / procedural schema，Dream 才能把“反复解决同类问题的过程”提炼成更高层结构
- 没有 procedural layer，Dream 就只能做摘要和去重，做不到真正的“能力沉淀”

所以可以把这条链理解成：

- `v1.6`：长出代谢器官
- `v1.7`：长出时间感
- `v1.8`：长出程序记忆
- `v1.9`：把这些东西接成代谢循环

---

## v1.9 的系统边界

Dream 要做强，但不能越界。

### 自动可以进化的层

这些属于 Dream 应该持续自动优化的对象：

- candidate graph 的连接强度
- wake-up 的分桶预算分配
- episodic -> semantic 的蒸馏候选
- semantic -> procedural 的 skill 候选
- relation cluster 的合并与拆分建议
- retrieval weighting 的经验性调优信号
- memory hot / warm / cold 分层

### 不能自动进化的层

这些不能交给 Dream 自主改写：

- confirmed rule 的直接删除
- confirmed fact 的无痕覆盖
- truth row 的直接 SQL update/delete
- 无审核的 ontology 变更
- 无历史保留的“修正旧记忆”

一句话概括就是：

> Dream 可以自动改“候选层、连接层、权重层、预算层”；
> 不能自动改“已生效真值层”。

这是 `harness-mem` 和 autonomous assistant runtime 的根本分叉。

---

## v1.9 的代谢循环

`v1.9` 最终应该长成一个固定循环，而不是离散功能点。

### Phase 1：Replay Window 选择

Dream 先决定“这次要重放哪些东西”。

输入候选包括：

- 最近 N 个 session 的 episodic observation
- 最近一段时间的 retrieval hit / miss 日志
- 最近 confirm / reject 的 review outcome
- 最近新增或 superseded 的 semantic fact
- 最近新增的 skill candidate 或低成功率 skill

选择原则：

- 最近发生的，不一定最重要
- 高频命中的，不一定最稳定
- 低频但高影响的，也不能丢

所以 replay window 必须是多信号选取，而不是单纯“最近 24 小时全扫”。

### Phase 2：Compression

对 replay window 做压缩与聚类：

- 近义 observation 合并
- 重复失败模式聚类
- 相似 relation candidate 合并
- 已过期上下文下沉为冷层

这一层的目标不是改 truth，而是降低噪声密度。

### Phase 3：Reinforcement

找出值得强化的对象：

- 高频命中的 semantic fact
- 多次被用户确认的规则
- 在多个 session 中重复成功的 skill pattern
- 经常共同出现的实体或关系

强化方式可以包括：

- 提升 confidence prior
- 提升 wake 注入优先级
- 提升 retrieval rerank 权重
- 形成更高层 candidate

### Phase 4：Weakening / Supersede

找出应该弱化的对象：

- 长期零命中的旧规则
- 已被新事实 supersede 的旧关系
- 只在一次临时上下文中有效的 observation
- 成功率持续偏低的 procedural skill

注意：

- 弱化不是删除
- 弱化首先表现为降权、出热上下文、进入冷层、等待审核

### Phase 5：Structure Synthesis

这是 `v1.9` 真正比“自动摘要”更高一级的地方。

Dream 不只是整理旧内容，而是要生成新结构，例如：

- 新的 skill candidate
- 新的 relation family
- 新的 project convention cluster
- 新的 troubleshooting pattern
- 新的 memory subtype

如果没有这一步，Dream 只是 maintenance；
有了这一步，Dream 才开始像 evolution。

### Phase 6：Review Surface

所有影响 truth 的结构变化，最后都应该落到 review surface：

- confirm
- reject
- supersede confirm
- merge confirm
- archive confirm

Dream 的价值不是绕过人，而是：

> 把人类 reviewer 要面对的内容，从几万字原始 session，
> 压缩成几十条高价值的结构化决策。

---

## v1.9 需要的新状态对象

如果要把 Dream 做成 metabolism，现有 schema 之外，至少要补一层“代谢状态”。

候选状态对象可能包括：

| 对象 | 作用 |
|------|------|
| `MemoryLink` | 表示节点之间的连接强度，而不是只有孤立条目 |
| `MemoryHeat` | 表示记忆当前处于 hot / warm / cold 哪一层 |
| `ReinforcementSignal` | 记录 retrieval hit、confirm hit、co-occurrence 等强化信号 |
| `WeakeningSignal` | 记录低命中、过期、失败等弱化信号 |
| `MergeSuggestion` | 表示 Dream 建议把若干 candidate / fact 聚成一个抽象单元 |
| `SupersedeSuggestion` | 表示 Dream 建议某事实应取代另一事实，但等待审核 |
| `DreamRun` | 记录一次 Dream replay 的输入窗口、输出建议、耗时与统计 |

其中最关键的不是名字，而是：

- “内容”与“连接”要分开建模
- “当前有效”与“历史曾经有效”要分开建模
- “真值”与“代谢建议”要分开建模

---

## 触发方式：不做 daemon，但要支持代谢周期

`v1.9` 需要周期性，但不等于必须引入常驻 runtime。

### 推荐形态

- `harness-mem dream`：显式 CLI 入口
- MCP / API 触发：让外部 agent 或 orchestrator 主动调用
- 外部 scheduler 触发：由宿主环境决定何时跑，不由本仓常驻守护

### 不推荐形态

- 内置无限循环 daemon
- 关终端后继续跑的 assistant lifecycle
- 主动自启动的 Proactive agent

也就是说，`v1.9` 允许有“周期”，但不要求本仓自己承担“生命体”。

---

## 评估指标：不要把 v1.9 做成玄学

如果 `v1.9` 上线，只说“更像人脑了”是没有意义的，必须有可以验证的代谢指标。

### 结构指标

- candidate -> confirmed 的转化率
- supersede suggestion 的审核通过率
- relation merge 的稳定度
- procedural candidate 的复用率

### 检索指标

- wake-up 命中价值率
- semantic bucket 被 episodic 噪声淹没的比例
- stale fact 被默认注入的比例
- retrieval hit after Dream vs before Dream

### 代谢指标

- 压缩率：Dream 前后 observation / candidate 的信息密度变化
- 强化率：高价值记忆在 Dream 后的命中提升
- 弱化准确率：被降权对象是否真的低价值
- 新生结构价值率：新生成 skill / relation / cluster 的确认通过率

### 安全指标

- Dream 生成建议中误伤 confirmed truth 的比例
- 无审计链结构变更数，目标恒为 `0`
- rollback 触发次数

如果这些指标建不起来，`v1.9` 很容易沦为“自动做了很多事，但谁也说不清有没有变好”。

---

## v1.9 的主要风险

### 1. 自我强化错误

Dream 如果把“被检索到”误当成“是真的”，就会形成自我回音室。

防线：

- retrieval hit 只能是强化信号之一，不是真值信号
- confirm / reject 结果权重要高于纯命中频次

### 2. 过度压缩

Dream 可能把有细微差异的几条事实错误合并，损失重要上下文。

防线：

- merge suggestion 只进候选层
- 支持保留原子 observation 的 provenance 回链

### 3. 图膨胀

如果什么都建边，系统会迅速变成不可控的噪声图。

防线：

- MemoryLink 必须有最小激活阈值
- 多跳图查询默认限制跳数与预算

### 4. 指标绑架

Dream 可能被优化成“提高确认率”，而不是“提高真值质量”。

防线：

- 不能把 accept rate 当唯一 KPI
- 必须同时看 stale injection、历史冲突、retrieval usefulness

### 5. 越界成 runtime

Dream 做着做着，很容易滑向“那不如顺手加主动唤醒、后台运行、长期代理人格”。

这条路对本仓是越界。

`harness-mem` 到 `v1.9` 仍然应该是：

- memory layer
- metabolism engine
- review-driven evolution loop

而不是完整 assistant runtime。

---

## v1.9 不做的事

为了防止 scope 膨胀，提前写死：

1. **不做 AI 自治删真值**
   所有 confirmed truth 变更都必须保留历史并经过 review。

2. **不做 always-on daemon**
   Dream 可以被周期触发，但不引入 KAIROS / Proactive 风格生命周期。

3. **不做“更像人脑”式叙事绑架**
   人脑类比只服务于系统设计，不作为正确性的论据。

4. **不做无约束自增图谱**
   图关系必须有预算、阈值、跳数限制、审计链。

5. **不做绕过 candidate layer 的自学习**
   即使 Dream 很强，也只能先进 candidate / suggestion 层。

---

## 一句话结论

如果 `v1.6 - v1.8` 都是在回答：

> “AI 应该记住什么？”

那么 `v1.9` 回答的是：

> “AI 的记忆系统，如何像一个有代谢的生命体那样，
> 持续压缩、强化、弱化、重组，并生成新的结构？”

所以 `v1.9` 的真正目标不是“自动记更多”，而是：

> **让记忆系统自己参与自己的演化，
> 但始终在可审计、可回滚、可审核的边界之内。**
