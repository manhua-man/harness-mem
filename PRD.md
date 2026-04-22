# Harness-Mem PRD

版本：v0.1  
日期：2026-04-18  
状态：Draft

## 1. 产品概述

`harness-mem` 是一个面向多客户端 AI coding/agent 工具的本地优先记忆运行时。

它的目标不是做某一个 IDE 或某一个模型的专属插件，而是提供一套统一的记忆内核，让 `Claude Code`、`Claude Desktop`、`Cursor`、`Gemini CLI`、`OpenCode` 等客户端可以共享：

- 持久记忆
- 项目级历史检索
- 启动上下文唤醒
- 低 token 的渐进式召回
- 可配置的自动保存与自动注入

`harness-mem` 的产品方向是：

- 吸收 `MemPalace` 的本地优先、分层记忆、低预算检索思路
- 借鉴 `claude-mem` 的自动化体验、hooks、跨客户端接入方式
- 避免把产品做成“Claude 专属插件”或“单一 IDE 的耦合实现”

一句话定义：

> `harness-mem` 是一个跨客户端、可插拔、低上下文开销的 AI 记忆底座。

## 2. 背景与问题

当前主流 AI coding/agent 客户端都存在相似问题：

1. 会话上下文短，重开后丢失项目历史
2. 跨工具切换时，记忆割裂
3. 为了“让模型记住”，用户只能反复粘贴背景材料，token 消耗高
4. 大多数记忆方案要么只适配单一客户端，要么强依赖云端和模型 API
5. 自动记忆方案往往黑盒，难以控制“注入多少、什么时候注入、花多少 token”

对开发者来说，最理想的状态不是“模型什么都自动记住”，而是：

- 近期工作自动保留
- 长期知识可结构化沉淀
- 只有在需要时才加载更深层的历史
- 同一份记忆可以被多个客户端重用

## 3. 产品目标

### 3.1 总目标

构建一套本地优先、多客户端共享的 AI 记忆系统，兼顾：

- 自动化体验
- 检索质量
- 低 token 消耗
- 可解释性
- 可迁移性

### 3.2 子目标

1. 提供统一的记忆核心，而不是每个客户端各做一套
2. 提供统一的 MCP 搜索接口，支持渐进式检索
3. 提供最小可行的自动保存机制，支持 hooks / transcript import / 手动保存
4. 支持“轻注入 + 按需深查”的上下文策略
5. 允许不同客户端根据自身能力选择 `full mode` 或 `search mode`

## 4. 非目标

以下内容不作为 v1 必做项：

- 做一个完整的 IDE
- 替代现有大模型客户端
- 提供云端托管服务
- 做通用团队协作文档平台
- 在所有客户端上都实现完全相同的自动化能力
- 做“自动总结一切”的重模型依赖流水线

## 5. 目标用户

### 5.1 主要用户

- 在多个 AI coding 工具之间切换的个人开发者
- 长期维护大型仓库、需要项目记忆的工程师
- 希望降低重复背景输入成本的 agent 使用者

### 5.2 次要用户

- 需要本地优先、可审计记忆系统的技术团队
- 想把记忆能力嵌入自己 agent/harness 的开发者

## 6. 核心产品原则

### 6.1 Local-first

默认本地存储、本地检索、本地索引。非必要不依赖云端。

### 6.2 Progressive Disclosure

先给轻量索引，再给时间线，再取详情，避免一次性把整段历史塞进 prompt。

### 6.3 One Core, Many Adapters

记忆核心只有一套；不同客户端只是接入层不同。

### 6.4 Verbatim-first, Summary-second

原始记录优先，摘要是辅助层，不让系统完全依赖 LLM 压缩后的二手表述。

### 6.5 Explicit Budget Control

用户需要知道：

- 注入了多少上下文
- 什么时候触发了深检索
- 什么时候使用了模型做总结或重排

## 7. 产品形态

`harness-mem` 由三层组成：

### 7.1 Memory Core

负责：

- 原始会话与事件存储
- 结构化项目/主题组织
- 检索与召回
- 上下文唤醒
- MCP 工具暴露

### 7.2 Adapter Layer

每个客户端一个 adapter，负责：

- hooks 集成
- transcript 导入
- MCP 配置与启动
- 会话起止生命周期对接

### 7.3 Policy Layer

负责：

- 默认注入策略
- 自动保存策略
- token budget 策略
- 不同客户端的能力降级策略

## 8. 关键能力

### 8.1 统一记忆存储

支持存储：

- 用户 prompt
- 工具调用轨迹
- 文件读写观察
- 结构化 observation
- 可选 session summary
- 手工知识文档

### 8.2 启动上下文唤醒

新会话启动时，根据：

- 当前项目
- 最近会话
- 高频主题
- pinned knowledge

生成轻量级 `wake-up context`。

### 8.3 渐进式搜索

MCP 检索链路至少支持：

1. `search`
2. `timeline`
3. `get_observations`

必要时扩展：

- `wake_up`
- `status`
- `save_note`
- `ingest_transcript`

### 8.4 多模式接入

#### Full Mode

适用于支持 hooks / plugin / lifecycle 的客户端：

- 自动捕获
- 自动保存
- 自动轻注入
- MCP 搜索

#### Search Mode

适用于只支持 MCP 或外部调用的客户端：

- MCP 搜索
- wake-up
- transcript import
- 手动保存

### 8.5 预算可控的上下文策略

默认不做“重注入”，而是：

- L0：固定短说明
- L1：轻量 wake-up
- L2：按需 recall
- L3：深度详情检索

## 9. 客户端适配目标

### 9.1 v1 目标平台

- Claude Code
- Codex

原因：

- 最容易挂 MCP
- 生命周期与仓库规则较明确
- 最适合先验证核心设计

### 9.2 v1.5 目标平台

- Cursor
- Gemini CLI

原因：

- 有较强实用价值
- 接入方式与 Claude Code 接近

### 9.3 v2 目标平台

- Claude Desktop
- OpenCode

默认先做 `search mode`，后续再看 hooks/extension 能力决定是否升级到 `full mode`。

## 10. Token 策略

`harness-mem` 的 token 优化不是“永远不用模型”，而是“只在值得的时候才用模型”。

### 10.1 默认策略

- 会话启动：只注入轻量 wake-up
- 普通问答：不自动塞入大段历史
- 历史追问：先 `search`
- 命中后：再 `timeline`
- 只有确认相关时：才 `get_observations`

### 10.2 摘要策略

默认不对每次 tool event 都做 LLM 摘要。

只在以下场景启用摘要：

- 会话结束
- 用户显式标记“值得记住”
- 需要生成便于跨会话复用的精炼记录

### 10.3 成本目标

v1 目标不是极限准确率，而是做到：

- 新会话基础唤醒上下文保持在低预算范围
- 大多数历史追问不需要全文注入
- 检索链路的平均 token 消耗显著低于“粘贴整段历史”

## 11. 功能范围

### 11.1 v1 范围

- 本地存储与索引
- wake-up context
- MCP search/timeline/get_observations
- Claude Code adapter
- Codex adapter
- transcript ingest
- 基础预算策略
- 只读 Web/CLI 状态接口

### 11.2 v1.5 范围

- Cursor adapter
- Gemini CLI adapter
- pinned memory
- session summary 可选化
- 基础观测面板

### 11.3 v2 范围

- Claude Desktop search mode
- OpenCode search mode
- knowledge graph
- policy profiles
- 多项目隔离与共享机制

## 12. 典型用户故事

### 12.1 跨客户端续接

作为一个开发者，  
我昨天在 Claude Code 修过 bug，今天换到 Codex，  
我希望不用重新讲背景，也能查到昨天的修复路径。

### 12.2 历史决策回溯

作为一个长期维护者，  
当我问“为什么这里改成这样”时，  
系统应先给我相关历史索引，而不是把整段旧会话塞进 prompt。

### 12.3 低预算长期记忆

作为一个大量使用 agent 的用户，  
我希望长期保留项目记忆，  
但不希望每次开会话都承担高额 token 消耗。

### 12.4 多端共享知识

作为一个同时用 Cursor、Gemini CLI 和 Claude Code 的用户，  
我希望共享一套项目记忆，而不是每个工具维护一份独立历史。

## 13. 成功指标

### 13.1 体验指标

- 新会话可以稳定拿到最近项目背景
- 用户不需要记住精确关键词也能检索历史
- 用户能理解“为什么注入这些上下文”

### 13.2 功能指标

- v1 至少支持 2 个客户端稳定接入
- MCP 搜索链路可用
- transcript ingest 可用
- wake-up context 稳定生成

### 13.3 成本指标

- 大多数项目历史问题不依赖全文注入
- 会话平均上下文注入量显著小于“人工粘贴背景”
- 摘要生成次数可控且可关闭

## 14. 风险与难点

### 14.1 平台能力不一致

不同客户端支持的 hooks、插件、MCP 生命周期差异很大。

### 14.2 自动捕获质量

若捕获粒度太细，会制造噪声；太粗，又失去记忆价值。

### 14.3 摘要依赖模型

若过度依赖 LLM 摘要，会牺牲 token 预算与可解释性。

### 14.4 存储膨胀

长期 verbatim 存储会产生体积和索引维护成本。

### 14.5 跨项目污染

如果项目隔离不好，wake-up 和搜索容易把错误项目的历史带进来。

## 15. 产品决策

当前先定下的关键决策如下：

1. `harness-mem` 不做 `claude-mem` 的 rename 版，而是独立产品
2. 核心思路更接近 `MemPalace`，但接入体验借鉴 `claude-mem`
3. v1 优先做 `Claude Code + Codex`
4. 默认采用“轻注入 + 按需深查”策略
5. 原始记录优先，摘要为辅助

## 16. 开发里程碑

### Milestone 1：Core MVP

- 本地数据模型
- 基础检索
- wake-up
- MCP server

### Milestone 2：Claude Code + Codex

- hooks/adapter
- transcript ingest
- 项目级配置
- 状态与预算输出

### Milestone 3：Search Expansion

- Cursor
- Gemini CLI
- pinned memory
- 更强的 recall 策略

## 17. Open Questions

以下问题暂未定案：

1. v1 是否直接引入 knowledge graph，还是先放到 v2
2. 摘要模型是否完全可插拔
3. 是否需要 Web Viewer，还是 CLI + MCP 已足够
4. transcript ingest 的标准中间格式如何定义
5. 不同客户端的权限/隐私边界如何统一表示

## 18. 外部方案吸收策略

`harness-mem` 不从零想象产品，而是明确吸收现有开源方案里已经被验证有效的机制。

这里的原则不是“把所有功能拼一起”，而是：

- 吸收核心机制
- 放弃强耦合实现
- 保留统一内核
- 延后高复杂度、重模型依赖特性

### 18.1 来自 MemPalace 的吸收点

应吸收：

- local-first 的产品立场
- 分层记忆栈
- wake-up 启动上下文
- verbatim-first 存储
- MCP 作为统一对外检索接口
- 可插拔 backend

不直接照搬：

- 过多的 palace 术语本体
- 一次性引入全部 MCP 工具

在 `harness-mem` 中的落点：

- 作为核心记忆层设计基础
- 作为 token 策略和 recall 分层的主要参考

### 18.2 来自 Claude-Mem 的吸收点

应吸收：

- 自动 capture 的工作方式
- hooks 驱动的生命周期接入
- 搜索链路的渐进式 retrieval
- worker/service + search API 的工程组织方式
- 跨客户端 adapter 的产品思路

谨慎吸收：

- 大量依赖 LLM 生成 observation/summary 的默认路径

在 `harness-mem` 中的落点：

- 作为 adapter 层与自动化体验设计参考
- 作为“近期工作自动记忆”的实现模板

### 18.3 来自 Claude Code Harness + Harness-mem 的吸收点

应吸收：

- `Plan -> Work -> Review -> Release` 的受控执行回路
- 与主 harness 深度耦合的 session event capture
- “本次做了什么、用了哪些工具、如何结束”的 session state 模型
- 对长运行任务和 compaction 的显式保护
- 让记忆不仅是“检索历史”，还是“恢复上一次任务状态”

谨慎吸收：

- 将产品定义成 Claude Code 专属增强层
- 过强绑定某一套 workflow 命令体系

在 `harness-mem` 中的落点：

- 作为 `workflow state memory` 的主要参考
- 作为“任务可恢复 / 可续跑”的记忆层设计基线

### 18.4 来自 Pro Workflow 的吸收点

应吸收：

- self-correcting memory
- “用户纠正 -> 生成候选 rule -> 用户确认 -> 永久保存”的学习闭环
- correction replay 到当前任务
- compact guard / compaction-aware state preservation
- 成本追踪与上下文预算意识

谨慎吸收：

- 将过多 workflow/agent/command 绑进内核

在 `harness-mem` 中的落点：

- 作为 `learning layer` 的核心能力
- 作为长期自我纠错系统，而不是单纯“检索历史”

### 18.5 来自 agentmemory 的吸收点

应吸收：

- hooks + MCP + REST 三路并存的接入策略
- BM25 + vector + graph 的 hybrid search 架构
- 4-tier memory consolidation
- 项目画像、文件历史、timeline、relations 这类高价值 memory primitives
- 单服务器共享多客户端记忆的设计

谨慎吸收：

- v1 就上过重的 runtime、viewer、trace console、超大工具面
- 将核心完全绑到特定 engine/runtime 上

在 `harness-mem` 中的落点：

- 作为 `advanced memory engine` 的上限参考
- 作为 v2 以后混合检索与多租户能力的设计输入

### 18.6 来自 Nemp Memory 的吸收点

应吸收：

- 极简安装体验
- plain JSON / human-readable 数据哲学
- auto-init 项目 tech stack 探测
- `CLAUDE.md` / `AGENTS.md` / 规则文件导出思路
- cross-provider export/import

谨慎吸收：

- 把所有东西都塞进 `CLAUDE.md`

在 `harness-mem` 中的落点：

- 作为 onboarding 和跨平台导出层参考
- 作为“低门槛模式”的产品路线

### 18.7 来自 Knowledge Graph 的吸收点

应吸收：

- git-native / file-native 的可审计知识层
- evidence-based rule synthesis
- co-change / dependency prediction
- 低 token 的 pointer-style knowledge injection
- 将规则和模块知识分布在 repo 中的思路

谨慎吸收：

- 过度依赖 bash-only 实现
- 过早做复杂推断引擎

在 `harness-mem` 中的落点：

- 作为 repo-native memory projection 层
- 作为长期“代码库知识节点”方案

### 18.8 来自 graph-memory 的吸收点

应吸收：

- 图结构 recall
- Personalized PageRank 这类 query-relative ranking 思路
- episodic traces
- community-aware recall

谨慎吸收：

- 一开始就引入复杂图算法与 embedding 流水线
- 把 v1 做成重型 graph engine

在 `harness-mem` 中的落点：

- 作为 v2/v3 的 advanced recall 路线
- 作为“复杂多会话知识域”的增强模块

### 18.9 来自 memory-bank-mcp + mcp-knowledge-graph 的吸收点

应吸收：

- MCP-first 的可读、可写、结构化记忆接口
- “文件就是记忆”的可移植存储思路
- 项目级与全局级 memory bank 的双层设计
- 实体 / 关系 / 观察 这种轻量结构化模型
- git 可版本控制、人工可读的长期知识库

谨慎吸收：

- 把 `harness-mem` 退化成纯 CRUD 笔记本
- 用过于原始的文本库替代真正的 recall / learning / lifecycle

在 `harness-mem` 中的落点：

- 作为 `structured writable memory` 层
- 作为与外部 MCP 客户端最通用的交换格式参考

## 19. 功能吸收决策表

### 19.1 v1 必收

- wake-up context
- MCP: `search / timeline / get_observations`
- transcript ingest
- hooks-based auto-save
- correction -> candidate rule -> confirm -> save
- lightweight replay learnings
- basic stack detection
- budget-aware context policy
- session state handoff
- task resume metadata
- structured writable memory store

### 19.2 v1.5 建议收

- export to `AGENTS.md` / `CLAUDE.md` / Cursor rules
- auto-sync project context
- cost tracker
- compact guard
- repo-native module memory projection
- REST API alongside MCP
- file history / session timeline / project profile primitives

### 19.3 v2 再收

- knowledge graph
- co-change inference
- community-aware recall
- graph ranking / PPR
- episodic trace recall
- hybrid BM25 + vector + graph retrieval
- team/shared memory
- viewer / replay / observability surface

### 19.4 明确不做

- 为了追求“自动化”而默认对每次工具调用都跑 LLM 总结
- 依赖单一模型厂商的私有接口
- 强绑定单一客户端的插件生态
- 先做巨大而难维护的 command/agent 集合

## 20. 产品差异化定位

`harness-mem` 的目标不是成为以下任一产品的复制品：

- 不是 `claude-mem` 的 rename 版
- 不是 `MemPalace` 的包装壳
- 不是 `pro-workflow` 的 workflow 套件翻版
- 不是 `Nemp` 的 JSON memory clone
- 不是 `knowledge-graph` 的 bash 移植版
- 不是 `graph-memory` 的 OpenClaw fork

它的差异化组合是：

1. `MemPalace` 的记忆内核观
2. `Claude-Mem` 的多客户端接法
3. `Claude Code Harness + Harness-mem` 的任务状态恢复能力
4. `Pro Workflow` 的自我纠错学习闭环
5. `agentmemory` 的重型记忆引擎与混合检索
6. `Nemp` 的轻部署与导出能力
7. `Knowledge Graph` 的 repo-native 知识投影
8. `graph-memory` 的高级 recall 思路
9. `memory-bank-mcp / mcp-knowledge-graph` 的 MCP-first 可写知识底座

## 21. 建议的 v1 产品主张

面向用户的第一版价值主张建议定为：

> `harness-mem` 让 AI coding agents 记住你的项目、学习你的纠正、并在新会话里只用极少上下文就恢复有效工作状态。

这个表述要同时覆盖三件事：

- 记住项目
- 学会偏好
- 控制 token
- 恢复任务状态

## 22. v1 核心闭环

v1 必须跑通的不是“所有高级记忆能力”，而是以下闭环：

1. 用户开始新会话
2. `harness-mem` 提供轻量 wake-up
3. 用户工作过程中产生文件/命令/观察轨迹
4. 用户纠正 agent
5. 系统提取 candidate rule
6. 用户确认保存
7. 系统记录本次任务状态与收尾方式
8. 下次会话自动加载相关记忆与任务续接信息
9. 相同错误出现频率下降

如果这一闭环不能成立，其他高级特性都不算成功。

## 23. 当前结论

`harness-mem` 不应该被定义成“某个 AI 客户端的记忆插件”，而应该被定义成：

> 一个本地优先、可插拔、跨客户端共享的 AI 记忆运行时。

它的第一阶段重点不是“把所有高级能力一次做完”，而是先把：

- 核心记忆层
- 渐进式检索
- 两个强客户端适配
- 可恢复的任务状态
- 明确的 token 策略

这四件事做稳。
