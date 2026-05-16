# v1.3 - v1.4 周期架构演进与技术债综合回顾

> **状态**：归档文档（取代原 `reviews/` 下的 8 份拆分评审及 `roadmap-v13-v14-proposal.md`）  
> **日期**：2026-05-16  
> **核心目标**：记录从“手动 CLI 工具”向“AI 原生/MCP 驱动的隐身运行时”转型的决策链条与遗留债务。

---

## 1. 产品愿景与定位演进

### 1.1 从工具到运行时
在 v1.3 周期前，Harness-Mem 被定位为“开发者的记忆工具”。经过“八方评审”（CEO、Eng、Office Hours 等），定位修正为：**Local-first AI Memory Runtime**。
- **Moat (护城河)**：坚持本地化（Local-first）、隐私优先、多客户端适配（Claude Code/Codex）、以及记忆的可编辑/可审计性。
- **核心魔法**：实现“Invisible Memory”——用户无需主动运行 CLI，记忆应通过 MCP 自动、静默地在 Session 间流动。

### 1.2 阶段性重点
- **v1.3**：完成 V1 体验闭环。引入 `purge` 命令解决记忆膨胀，通过 **Vector + FTS5 Hybrid Search** 填补语义检索鸿沟。
- **v1.4**：强化溯源（Provenance）与学习闭环。让每条规则都能追溯回原始会话，并将 Learning Loop 深度集成进 MCP 接口。

---

## 2. 检索技术架构的重大转向

### 2.1 放弃“时间偏置 (Temporal Bias)”
- **决策背景**：原计划通过加权近期记忆来优化召回，但经过 `LongMemEval` 基准测试验证，显式的时间权重反而降低了 R@5 召回率。
- **结论**：于 2026-05-12 彻底移除该功能，转而拥抱基于向量语义的 Hybrid Search。

### 2.2 确立 Hybrid Search 路线
- **架构方案**：保留 SQLite FTS5 作为“关键词/代码符号”检索的底座，引入 `sentence-transformers` (all-MiniLM-L6-v2) 处理“语义/意图”匹配。
- **原则**：Blob as truth, Index as cache。向量索引与 FTS5 索引在编排层进行线性加权合并（默认权重 FTS: 0.4, Vector: 0.6）。

---

## 3. 工程债务与治理（Linus & Health 视角）

### 3.1 核心痛点：`cli.py` 单体化
- **现状**：`cli.py` 膨胀至 1200+ 行，集成了解析、派发、业务逻辑和 UI 格式化。
- **债务**：dispatch 逻辑使用冗长的 if-else 链；Token 预算计算逻辑在 `status`、`profile`、`wake-up` 中多处重复。
- **治理建议**：在 v1.4+ 必须将子命令逻辑拆分至 `commands/` 目录，统一 Token 预算计算函数。

### 3.2 存储层测试缺口
- **风险**：`local_structured_store.py` 和 `sqlite_index.py` 承担了核心持久化重任，但缺乏独立的单元测试（主要靠集成测试间接覆盖）。
- **行动**：v1.3 周期内必须补齐存储层单元测试，特别是针对 FTS5 边界条件的校验。

### 3.3 类型安全与 Lint
- **现状**：存在 Pydantic v1→v2 迁移遗留的无效 import（如 `typing.Optional`）。
- **修复**：通过 `ruff --fix` 和 `mypy` 专项治理，重点解决 `list? [T]` 的可选列表迭代安全问题。

---

## 4. UX 设计准则：引导与渐进披露

### 4.1 成功模式：Suggested Next Step
- **准则**：`quickstart` 和 `doctor` 命令建立的“状态感知 -> 建议下一步”模式被证明是降低新手门槛的神技。
- **演进**：所有输出命令（如 `status`, `wake`）应在尾部追加标准化的“阶段标识”与“建议命令”。

### 4.2 交互式平衡
- **策略**：`correct` 和 `handoff` 默认进入交互模式。
- **优化**：在 `--help` 中需明确标注交互行为，避免用户误以为只能通过参数运行。

---

## 5. 遗留待办 (High Priority Debt)

1.  **[P0]** 补齐 `storage/` 层的单元测试。
2.  **[P0]** 将 MCP 工具中的 `reject_rule_candidate` 补齐（当前仅 CLI 支持，MCP 不对称）。
3.  **[P1]** 拆解 `cli.py` 单体，重构 dispatch 派发逻辑。
4.  **[P1]** 在 `wake-up` 输出中对截断内容明确标注 `[...truncated]`，防止 LLM 产生幻觉。
5.  **[P2]** 完善 PyPI 发布流程，降低外部贡献者安装门槛。

---

> **结论**：v1.3/v1.4 周期不仅是功能的堆砌，更是对 **"Local-first AI Runtime"** 这一独特生态位的深度确认。清理过往文档后，团队应聚焦于 `cli.py` 的解耦与检索能力的数值达标（R@5 ≥ 94%）。
