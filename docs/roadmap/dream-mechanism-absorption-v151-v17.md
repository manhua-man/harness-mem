# 设计稿：吸收 Claude Dream 机制，而不照搬产品形态

> 状态：历史设计稿（draft archive），不是当前版本路线图。相关 `v1.5.1` - `v1.7`
> 已完成；当前版本状态以 `docs/roadmap-status.md` 与 `CHANGELOG.md` 为准。
>
> 适用范围：`harness-mem` v1.5.1 / v1.6 / v1.7 设计收敛
>
> 目标：吸收 `Claude-Code-rev` 中已经被源码验证过的 memory-consolidation 机制，但保持 `harness-mem` 作为 **local-first, auditable, human-in-the-loop memory runtime** 的产品边界不变。

---

## 为什么写这份设计稿

`Claude-Code-rev` 里真正值得参考的，不是 `KAIROS`、`Proactive`、daemon 化这些“完整 agent runtime”层，而是它在 memory consolidation 上已经验证过的一些机制：

- `mtime = lastConsolidatedAt` 的锁文件技巧
- “时间门 -> 会话门 -> 锁门”的便宜到昂贵 gate 顺序
- consolidation / distill 期间的只读工具边界
- 后台整理任务与主对话解耦
- 对记忆索引体积、摘要预算的自我克制

但本仓当前产品定位已经在既有文档里写得很清楚：

- `harness-mem` 的主链是 `ingest -> distill -> review -> use`，不是常驻 agent runtime
- moat 是 **local-first、可编辑/可审计、多人类审核员可追溯**
- v1.x 路线是先把 memory baseline 做扎实，再往 invisible memory 演进，而不是立刻引入 daemon / proactive assistant

因此，这份设计稿的核心原则是：

1. 借机制，不借产品壳。
2. 借安全边界，不借无人审核自治。
3. 借自动化触发，不破坏 `human-in-the-loop`。

---

## 三层吸收结论

### 第一层：直接吸收（v1.5.1 - v1.6 内落地）

这些机制已经和本仓现有路线高度对齐，应该直接进入当前设计：

1. **锁文件 `mtime = cursor` 技巧**
2. **三段 gate：时间 -> 新 session 数 -> 锁**
3. **scan throttle**
4. **distill / consolidation 的只读边界**

### 第二层：延后吸收（v1.7 - v1.8 再判断）

这些机制值得保留，但不应抢跑到当前版本：

1. **按类型分桶的预算约束**
2. **后台子进程 / 子代理式整理任务**
3. **摘要索引的强上限理念**

### 第三层：明确不做（写进边界，避免后续评审回潮）

这些点即使在对方系统里成立，也不应进入 `harness-mem` v1.x：

1. **AI 自治删除或改写已生效记忆**
2. **常驻 daemon / proactive / KAIROS 风格运行时**
3. **以 markdown memory dir 替代 SQLite / structured store**

---

## 吸收后的产品边界

### 保留不变的边界

- **source of truth 仍然是 SQLite + structured memory**
- **distill 输出仍然先进入候选或建议层，不直接替换已确认事实**
- **用户仍然可以追溯：这条规则从哪来、何时被 supersede、旧版本是什么**
- **runtime 形态仍然是 MCP-first + CLI bootstrap，不引入常驻后台进程作为主路径**

### 明确不跟随的边界

- 不做 `MEMORY.md + topic files` 作为主存储
- 不做“关掉终端还继续工作”的 assistant lifecycle
- 不做“LLM 发现旧记忆错了就直接删”的自治闭环

---

## 机制映射表

| Claude Dream 机制 | 借鉴方式 | 落点版本 | 在本仓的改写 |
|---|---|---|---|
| `.consolidate-lock` 的 `mtime = lastConsolidatedAt` | 直接吸收 | v1.5.1 | 改为 auto-ingest cursor，不做 dream cursor |
| 时间门 -> 会话门 -> 锁门 | 直接吸收 | v1.5.1 | 用于 `wake-up` 内置 auto-ingest，先挡掉无意义扫描 |
| scan throttle | 直接吸收 | v1.5.1 | 改成**持久化** throttle，不依赖长驻进程内状态 |
| consolidation 只读 Bash | 直接吸收 | v1.6 | 定义 distill 安全边界：读 observation / search / compare，不能 delete / mutate truth |
| MEMORY.md 行数和体积硬上限 | 理念吸收 | v1.6 | 改为 wake-up 各 type bucket 独立 token 配额 |
| forked agent 跑 dream | 延后吸收 | v1.8 | 仅在 procedural analysis 或重型离线整理时评估 |
| 梦境自动删旧记忆 | 明确不做 | 不引入 | 改成 supersede 标记，不删除历史 |
| KAIROS / Proactive | 明确不做 | 不引入 | 交给 Letta 等 runtime，`harness-mem` 只做 memory layer |

---

## v1.5.1：wake-up auto-ingest 吸收锁文件与 gate 机制

> 2026-05-16 更新：
>
> 当前代码里**已经实际落地**的 `v1.5.1`，不再只是轻量 profile cursor 方案，而是把这三条 Dream 机制吸收到 `wake-up` auto-ingest 主路径：
>
> - per-project `.ingest-lock`
> - `mtime = 最近一次成功 auto-ingest cursor`
> - “时间 -> 会话 -> 锁”三段 gate
> - 持久化 `.ingest-scan-stamp`
>
> 同时保留本仓边界：只写 verbatim observations，不跑 LLM distill，不引入 daemon / proactive runtime。

### 目标

让用户在下一次 `wake-up` 时自动看到刚产生的新会话，而不必手动执行 `ingest`，同时避免每次 `wake-up` 都做昂贵扫描。

### 采用机制

#### 1. 使用锁文件 `mtime = ingest cursor`

借鉴 `Claude Dream` 的做法，但做一个关键改写：

- **不使用全局单文件** `~/.harness-mem/data/.ingest-lock`
- **改为每项目一个 cursor/lock 文件**

推荐路径：

```text
~/.harness-mem/data/projects/<project-slug>/runtime/.ingest-lock
```

语义：

- 文件 `mtime` = 最近一次**成功完成** auto-ingest 的时间戳
- 文件内容 `body` = `pid / state / last_session_id / updated_at`

这样做的原因：

- `harness-mem` 是多项目 memory runtime，全局单锁会把不同项目的 ingest cursor 混在一起
- per-project cursor 与现有 `use <project-name>` / active project 语义一致
- `mtime` 可以稳定保留“上次成功 ingest 的 cursor”语义
- 锁文件 body 则补充“当前是否 running、是谁持锁、最新 cursor session 是谁”这些运行态信息
- stale 判断以 `updated_at` 为准，而不是复用 `mtime`，避免把“运行态心跳”污染成新的成功 cursor

#### 2. 采用“三段 gate：时间 -> 会话 -> 锁”

顺序必须维持为由便宜到昂贵：

1. **时间门**
   - 配置项：`[wake] auto_ingest_min_interval_seconds`
   - 默认值：`300` 秒
   - 如果距上次成功 ingest 未超过阈值，直接跳过

2. **会话门**
   - 仅在时间门通过后，检查 cursor 之后是否出现了新 session
   - 默认阈值：`1`
   - 只允许做“轻量候选计数 / mtime 比较”，不进入完整 ingest 流程

3. **锁门**
   - 仅在前两门通过后尝试持锁
   - 采用 PID + stale TTL 回收机制
   - stale 判断可沿用 `1h` 级别默认值

这样可以把绝大多数“其实没新东西”的 `wake-up` 请求挡在最便宜的阶段。

#### 3. scan throttle 必须持久化，而不是照搬进程内变量

这里要和 `Claude-Code-rev` 做一个显式分歧。

对方的 `autoDream` 运行在长生命周期进程里，所以 `lastSessionScanAt` 可以放在 closure 内存中。但 `harness-mem wake-up` 是短生命周期 CLI / MCP 调用，单次进程退出后进程内状态就没了。

因此本仓的 throttle 不能照搬成内存变量，必须持久化。

推荐路径：

```text
~/.harness-mem/data/projects/<project-slug>/runtime/.ingest-scan-stamp
```

语义：

- `mtime` = 最近一次执行“新 session 探测”的时间
- 当时间门通过但会话门失败时，更新 scan stamp，而**不更新** ingest cursor
- 下一次短时间内 `wake-up` 时先看这个 stamp，命中 throttle 就直接跳过扫描

这样可以同时满足：

- 不污染“成功 ingest cursor”
- 避免高频 `wake-up` 下重复扫描 session 目录

### 行为约束

- auto-ingest 只允许写入 **verbatim observations**
- **不跑 LLM distill**
- 任何超时或错误都不阻断主 `wake-up`
- 输出沿用 v1.5.1 已定的三种固定摘要：
  - `Auto-sync: up to date`
  - `Auto-synced: N new sessions ingested (Xms)`
  - `Auto-sync skipped: reason`

### 与当前路线图的衔接

这部分不是新方向，而是对 `docs/roadmap-v15x.md` 中 v1.5.1 P0 的实现细化；截至 2026-05-16，已经进入当前代码：

- P0 轻量 auto-ingest
- P0 ingest 预算与可见性
- P0 `--no-auto-ingest` 和 config 开关

这份设计在该 P0 下补上了“如何把 cursor / 锁 / throttle 做得更稳”，并已转化为实际实现。

---

## v1.6：把 Dream 的“自我克制”吸收到记忆分型与安全边界

### 1. 记忆三层分型的预算，不学文件索引，学预算纪律

`Claude Dream` 里的 `MEMORY.md 200 行 / 25KB` 是一种好的“强制收敛”机制，但本仓不维护 markdown 索引文件，因此不照搬形态，只吸收预算思想。

在 v1.6 中，`wake-up` 的组装应从“全库混排 top-k”升级为“分型桶预算”：

- `episodic`：事件 / 原始 observation
- `semantic`：confirmed rules / relation facts / stable project facts
- `procedural`：预留桶，v1.8 前默认配额可为 0

建议约束：

- 每个 type bucket 有独立 token 配额
- 总 token 预算仍然有全局上限
- 默认策略优先保证 `semantic`，再填 `episodic`

推荐默认比例：

- `semantic`: 50%
- `episodic`: 50%
- `procedural`: 0%（v1.8 之前保留字段，暂不喂给 wake）

理由：

- 当前最容易被淹没的是 semantic 规则，而不是 episodic 数量
- procedural 还没成型，不应该抢预算

### 2. distill / conflict detection 的只读边界

`Claude Dream` 的一个成熟点是：在 consolidation 场景里提前收紧工具权限，禁止写状态的 shell。

本仓在 v1.6 必须把这个边界写进设计，而不是等 v1.7 / v1.8 引入更强 distill 能力后再补：

- distill 阶段允许：
  - 读 observations
  - 读 structured entries
  - 搜索 / 比较 / 聚类 / 生成候选建议
- distill 阶段不允许：
  - 直接删除 observation
  - 直接修改 confirmed rule
  - 直接执行 SQL delete / update truth rows
  - 直接 compact / purge

distill 的所有“写动作”都必须降级成建议层输出，例如：

- `RuleCandidate`
- `MergeSuggestion`
- `ConflictCandidate`
- `SupersedeCandidate`

换句话说：

> LLM 可以读全库、比较全库、提出建议，但不能绕过审核直接改变 truth。

这既吸收了对方的安全护栏，也保住了本仓的审计护城河。

---

## v1.7：用 supersede 取代 dream-style 自治删除

### 核心差异化

`Claude Dream` 的自然倾向是“发现旧事实被推翻，就直接修掉旧记忆”。这和本仓路线冲突。

本仓 v1.7 应明确：

- **不删除旧事实**
- **不静默覆盖旧规则**
- **只标记时间有效区间与 supersede 关系**

### 建议语义

对 `RelationFact` / `ConfirmedRule` 增加：

- `valid_from`
- `valid_to`
- `recorded_at`
- `supersedes`（可空）

当新的候选事实被确认后：

- 新事实成为 currently valid
- 旧事实的 `valid_to = now`
- 保留旧事实全文与 provenance

这样可以满足三件事：

1. 当前 `wake-up` 默认只喂 currently-valid 事实
2. 用户仍然可以查历史
3. 冲突演进可以审计，而不是“被 AI 改没了”

### 与对方机制的关系

这里的结论不是“Claude Dream 错了”，而是：

- 对方系统优化的是 autonomous assistant
- 本仓优化的是 auditable memory runtime

所以同一个“记忆更新”问题，两边应该做不同选择。

---

## v1.8：仅在 procedural analysis 里评估后台子进程模型

`Claude Dream` 的 forked subagent 模型值得保留，但不应提前进入 v1.5.x / v1.6。

### 为什么暂不前移

- 当前 `distill` 仍然是显式 CLI / skill 动作
- v1.5.1 的核心价值在自动 ingest，不在后台大模型整理
- 提前引入后台子进程会让产品边界往 daemon / runtime 方向漂移

### 适合引入的时机

只有当 v1.8 procedural memory 真的需要做这些重型离线任务时，再考虑：

- 重复流程发现
- skill candidate 聚类
- 跨 session 过程模式抽取

此时可以借鉴的只是“任务模型”：

- 主请求不阻塞
- 子进程只读分析
- 结果回写候选层

而不是把 `assistant lifecycle` 一并搬过来。

---

## 明确不做的事

为了避免未来评审再次把边界推歪，以下内容应明确写入“风险与不做的事”：

### 1. 不做完整 daemon 模式

不引入：

- KAIROS
- Proactive
- Sleep loop
- 关终端后继续跑的 assistant lifecycle

需要这类能力的用户，应使用：

- Letta 等 stateful runtime
- `harness-mem` 作为 memory layer 接入

### 2. 不做 AI 自治删除记忆

不允许：

- LLM 直接删除 confirmed rules
- LLM 直接删除历史 observation
- LLM 在没有候选 / 审核痕迹的情况下改写 truth

### 3. 不把 markdown memory dir 当成主存储

不引入：

- `MEMORY.md` 作为主索引
- topic markdown files 作为主 truth layer

本仓继续坚持：

- SQLite / JSON blobs / FTS / structured entities

必要时可以导出 markdown 视图，但不反转 source of truth。

---

## 版本落点汇总

### v1.5.1

- 当前已交付代码：per-project `.ingest-lock` 的 `mtime` 作为最近一次成功 auto-ingest cursor
- 当前已交付代码：`.ingest-lock` body 保存 `pid / state / last_session_id / updated_at`
- 当前已交付代码：按“时间 -> 会话 -> 锁”三段 gate 执行 auto-ingest
- 当前已交付代码：`.ingest-scan-stamp` 作为持久化 scan throttle
- 当前已交付代码：`wake-up` 内置 auto-ingest，且只写 verbatim observations，不跑 LLM distill
- 当前已交付代码：支持 `--no-auto-ingest` 与 `config.toml` 开关，并覆盖成功 / 无新增 / 超时 / 关闭路径

### v1.6

- 在记忆三层分型设计中加入“每个 type bucket 独立 token 配额”
- distill / conflict detection 引入只读边界
- 任何 LLM 写动作都降级为 candidate / suggestion，而不直接改 truth

### v1.7

- supersede 机制采用“标记不删”
- confirmed facts / rules 引入 bi-temporal 字段
- `wake-up` 默认只注入 currently-valid 事实，历史仍可查询

### v1.8

- 仅在 procedural memory 需要重型离线分析时，再评估子进程 / forked analysis 模型

---

## 最终结论

这次吸收的正确姿势不是：

> “把 Claude Dream 搬进来”

而是：

> “把已经被验证过的 consolidation 机制，翻译成适合 `harness-mem` 的 runtime 设计”

真正该吸收的是：

- 锁与 cursor 合一
- gate 顺序优化
- 扫描节流
- 只读安全边界
- 预算纪律

真正该坚持不变的是：

- SQLite 作为 truth
- 审核闭环
- supersede 而非删除
- memory layer 而非 daemon runtime

如果后续要把这份设计落实到 roadmap 文档本体，建议按顺序分三步回填：

1. 在 `roadmap-v15x.md` 的 v1.5.1 段补充 lock / cursor / throttle 细化
2. 在 `roadmap-vision-v16-v18.md` 的 v1.6 / v1.7 段补充 budget bucket 与 supersede 差异化
3. 在“风险与不做的事”中明确排除 `KAIROS / Proactive / 自治删记忆`
