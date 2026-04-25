# CEO/产品战略评审：harness-mem v1.3 & v1.4

> 评审日期：2026-04-25
> 基于 v1.2.0 版本状态、LongMemEval 基准测试结果及现有路线图文档

---

## 1. 核心价值主张与市场定位

**当前核心价值主张：** "Local-first, pluggable AI memory runtime for Claude Code and Codex"——一个本地运行的、可插拔的记忆运行时，让 AI 编码助手拥有跨 session 的持久记忆。

**定位评价：清晰，但不够尖锐。**

优势：
- Local-first 是真正差异点——MemPalace 依赖向量数据库，用户数据经过外部服务；harness-mem 的数据全在 `~/.harness-mem/data/`，JSON + SQLite，无需任何外部基础设施。
- "Pluggable" 为多 adapter 留了空间，目前已支持 Claude Code 和 Codex。
- V1 跑通了完整闭环（ingest → structured memory → wake-up → search → learning loop → task resume），不是半成品。

问题：
- 当前只绑定 AI 编码场景，target user 是开发者。这面够窄、够精准，但 "memory runtime" 这个描述暗示了更泛化的能力——V1 实际交付的是一个 "session memory toolkit"，而非通用 memory runtime。
- 与 MemPalace 的竞争叙事太纠缠。README 和 benchmark 报告花了大量篇幅解释"差距在哪、V2 要追"，这暗示读者"我们现在不如 MemPalace"。建议对外弱化对比，强调 local-first 这个 MemPalace 无法复制的优势。

**建议调整定位表述为：** "Local-first memory for AI coding sessions. Your Claude Code and Codex sessions never forget what they learned." 简单、直接、唯一卖点明确。

---

## 2. v1.3 和 v1.4 应该解决什么痛点

**我的判断：v1.3 和 v1.4 应该继续做 V1 体验的封口，而不是冲 V2 检索。理由：**

1. **检索提升有成熟的、低风险的工程路径。** 引入 sentence-transformers + FTS5 hybrid 是已知方案，benchmark 报告已经给出了路径（all-MiniLM-L6-v2 → hybrid → ReRanker）。这个可以（也应该）在 v1.x 周期内完成，但不应该成为版本主题——它更像是"基础设施升级"而非"新价值交付"。
2. **V1 体验还有明显的"最后一公里"缺口。** purge 命令缺失（Compact Guard 只有文字提示没有行动入口）、distill 粒度粗糙（只支持按 category 过滤）、learning loop 没有 web UI 入口。这些是用户每天都会碰到的摩擦点。
3. **扩平台适配（Cursor、Gemini CLI）的价值尚不明确。** 在 Claude Code + Codex 这组核心用户尚未体验完整闭环之前，分散精力去做更多适配器是 premature scaling。v1.5 计划可以保持，但不应该提前。

**用户（开发者）的真实痛点排序：**

| 痛点 | 严重程度 | v1.x 能解决？ |
|------|---------|-------------|
| 记忆随时间膨胀，wake-up 预算炸了 | 高 | 是——purge 命令 |
| 搜索时相关片段被噪音淹没 | 高 | 是——向量 hybrid |
| distill 只能按 category 筛，不能按时间/质量 | 中 | 是 |
| 想知道"这个记忆基于哪条 conversation" | 中 | 是——provenance 追溯 |
| 想在不离开 Claude Code 的情况下管理记忆 | 中低 | 是——MCP 增强 |
| Cursor/Gemini 用户无法用 | 低 | 否——推迟到 v1.5 |

结论：先解决"已有用户的高频痛点和数据膨胀风险"，再考虑扩平台。

---

## 3. v1.3 和 v1.4 建议 feature

### v1.3（2-3 周）：完成 V1 体验闭环

**Feature 1: `purge --before` 命令（Compact Guard 的行动闭环）**
- 现状：doctor 和 wake-up 已经提示"你的记忆在 L3/L4+"，但没有实际清理命令。
- 实现：`harness-mem purge --before 2026-03-01` 删除指定日期之前的 verbatim observations + structured entries。支持 `--dry-run` 预览删除数量。支持 `--category` 限定只清理特定类型的 structured memory。
- 理由：这是用户最直接喊疼的地方——budget 预警看着但做不了什么。
- 优先级：P0。v1.2.1 计划中就有，应作为 v1.3 的主角。

**Feature 2: 检索增强——向量嵌入 + FTS5 hybrid**
- 实现：集成 sentence-transformers（all-MiniLM-L6-v2），FTS5 BM25 分数与向量余弦相似度线性加权（alpha=0.5 起步）。
- R@5 目标：从 87.3% 提升至 94%+。
- 理由：benchmark 已经给出了路径，这是"基础设施升级"——做好后 v1.4 可以在上面搭建更好的 UX。
- 优先级：P1。工程上是低风险高回报，但在版本叙事上它是"基础修路"而非"新功能"。

**Feature 3: CLI 体验微调（渐进披露最后一公里）**
- `search` 输出增加 relevance score 显示
- `status` 增加每个项目的 memory 年龄分布（最老的 observation 多久了）
- `distill` 增加 `--since` 参数（只蒸馏某时间点之后的 session）
- 理由：这些是 CLI-design-expert 中渐进披露原则的应用延伸。
- 优先级：P2。

### v1.4（2-3 周）：Provenance 与 Learning Loop 强化

**Feature 1: Provenance 追溯**
- 每条 structured memory（MemoryEntry、ConfirmedRule、TaskHandoff）可追溯回原文：`harness-mem show <memory-entry-id>` 展示来源 observation 摘要 + 所在 session 链接。
- 理由：用户看到学习到的规则后最自然的疑问是"这是从哪段对话提炼的？"——V1 缺少这个链路。
- 优先级：P0。体验完整性的核心缺口。

**Feature 2: Learning Loop MCP 升级**
- 在 Claude Code 内通过 MCP 工具直接完成 correct → confirm/reject 流程，无需切换到终端。
- 增加 `suggest_rule` MCP 工具：基于当前 session 内容自动检测是否应生成 candidate rule。
- 理由：Learning Loop 是 V1 标志性差异化能力，但目前使用门槛高（要记命令、切换窗口）。把这个闭环缩到 Claude Code chat 内，用户留存会显著提升。
- 优先级：P1。

**Feature 3: 记忆质量评分与自动整理**
- 对 structured memory entries 加入 last-accessed 时间戳和 usage count
- 自动标记低质量/陈旧 entry（从未被 recall 的规则、从未 resume 的 handoff）
- `doctor` 中展示"N 条低质量 entries，建议 purge 或 review"
- 理由：记忆膨胀不只是体积问题，更是信噪比问题。用户需要工具来维持记忆质量，而非纯手动管理。
- 优先级：P2。

---

## 4. 应该推迟到 V2（v2.0+）的功能

| 功能 | 推迟理由 | 预计进入时间 |
|------|---------|------------|
| **Graph 记忆（实体关系图）** | 复杂度过高，且 V1 用户还未抱怨"缺少关系检索"。SQLite FTS5 + 向量足以覆盖 V1.x 需求。 | V2.0 |
| **跨客户端任务续接** | 需要在多个 adapter 间同步状态，涉及协议设计。当前 Claude Code 和 Codex 各自独立的 task handoff 已经够用。 | V2.0 |
| **Cursor adapter / Gemini CLI adapter** | 核心用户在 Claude Code + Codex 上，扩平台是增长策略而非留存策略。在 V1 体验封口之前不应分散资源。 | V1.5（保持原计划） |
| **Web UI / Dashboard** | CLI 是正确的最小化交付。Web UI 会增加前/后端维护成本，且不确定用户是否真的想要。应等有明确用户需求信号再投入。 | V2+（观察） |
| **ReRanker（cross-encoder）** | 效果好但推理成本高（每次搜索都要跑 cross-encoder）。在向量 hybrid 达到 94%+ 后，再评估是否有必要上 ReRanker。 | V2.0（benchmark 驱动） |
| **多用户/协作** | 当前是 single-user local-first 工具。多用户涉及权限、同步、合并冲突——完全是另一个产品。 | V3+（不承诺） |

---

## 5. 关键成功指标

### v1.3 成功指标

| 指标 | 目标值 | 如何测量 |
|------|-------|---------|
| LongMemEval R@5 | ≥ 94% | benchmark 脚本运行 |
| purge 命令可用 | 全面测试通过，含 dry-run 和权限校验 | 集成测试 |
| Compact Guard 闭环率 | 收到预警的用户中 ≥70% 能找到 purge 命令 | 采集 doctor/wake-up 后的命令统计 |

### v1.4 成功指标

| 指标 | 目标值 | 如何测量 |
|------|-------|---------|
| Provenance 覆盖率 | 100% structured entry 可追溯 | 逐类型验证 |
| Learning Loop MCP 使用率 | 新 candidate rule 中 ≥40% 通过 MCP 创建 | 日志统计 |
| 用户满意度信号 | 无"我怎么清理记忆""这规则从哪来的"类 issue | Issue tracker 监控 |

### 整体 V1.x 退出条件（何时可以开始 V2）

1. FTS5 + 向量 hybrid 的 R@5 ≥ 94%（检索能力证明）
2. purge → distill → wake-up 闭环无断裂（体验完整性证明）
3. Learning Loop 的 MCP 使用率 ≥ 30%（差异化能力采用率证明）
4. 至少 3 个外部用户（非作者）已完成从 quickstart 到 task resume 的完整流程（外部验证证明）

满足上述 4 条后，V1.x 可被认为是一个 shipping-ready 的产品，而非仅作者的工具。
此时再启动 V2（graph、跨客户端续接、扩平台），基础会更扎实。

---

## 总结路线图

```
v1.3（2-3 周）         v1.4（2-3 周）         v1.5（计划）
┌────────────────┐    ┌────────────────┐    ┌────────────────┐
│ Purge 命令     │    │ Provenance 追溯│    │ Cursor adapter │
│ 向量 hybrid    │───→│ Learning Loop  │───→│ Gemini CLI     │───→ V2
│ CLI 体验微调   │    │ MCP 升级       │    │ adapter        │
│                │    │ 记忆质量评分   │    │                │
└────────────────┘    └────────────────┘    └────────────────┘
     R@5 ≥ 94%          闭环完整性           多平台覆盖
```
