# v1x-retention-stability-reset Tasks

## v1.3 Tasks

### P0 Tasks (Must Complete)

#### T-1: purge 子命令
- [x] 实现 `purge --before <DATE> [--dry-run] [--category]`
- [x] 软删除/compact 标记，不做物理清除
- [x] 测试 soft-delete 后不参与 wake-up / search

#### T-2: doctor/wake 集成 purge 建议
- [x] doctor 在 L3/L4+ 时显示 purge 建议
- [x] wake 在 L3/L4+ 时显示 purge 建议和示例命令
- [x] 示例命令可直接复制使用

#### T-3: 状态型命令统一格式
- [x] quickstart/doctor/status/profile/wake 共用 Phase/Next step/Why 格式
- [x] 提炼 phase formatter 到 formatters.py

#### T-4: CLI 清晰度改进
- [x] timeline --help 显示真实默认值
- [x] search 无 query 时引导式提示，不抛 argparse error
- [x] correct/handoff help 标注交互式行为

#### T-5: MCP reject_rule_candidate
- [x] 补齐 reject_rule_candidate 实现
- [x] 与 confirm_rule_candidate 对称

#### T-6: 输出格式统一
- [x] wake-up 截断统一加 [...truncated]
- [x] 搜索结果展示排序依据或 score
- [x] show 增加 -o/--observation-id，-i/--id 保留兼容别名

### P1 Tasks

#### T-7: HybridSearchLayer
- [x] 引入 HybridSearchLayer 类
- [x] 支持 mode=auto|fts|hybrid
- [x] 向量模型懒加载
- [x] 无 embedding 时退化到纯 FTS

#### T-8: CI Matrix
- [x] GitHub Actions 增加 Windows/macOS/Linux matrix
- [x] 验证所有平台测试通过

#### T-9: 类型清理
- [x] 修复 Optional[list[T]] 问题
- [x] 修复 None guard 遗漏
- [x] 修复 adapter 类型问题

#### T-10: 单元测试
- [x] sqlite_index 直接单元测试
- [x] structured store 单元测试

#### T-11: Codex Adapter 防御
- [x] 增加异常捕获
- [x] 增加损坏文件防御
- [x] 不再静默吞错

#### T-12: shell completion
- [x] 实现 shell completion
- [x] 测试 bash/zsh/fish

#### T-13: 事件日志
- [x] 轻量本地事件日志
- [x] 统计 next-step 命令采用率
- [x] 日志只写本地数据目录

---

## v1.4 Tasks

### P0 Tasks (Must Complete)

#### T-14: Provenance 字段
- [x] MemoryEntry 增加 provenance 字段
- [x] ConfirmedRule 增加 provenance 字段
- [x] TaskHandoff 增加 provenance 字段

#### T-15: Provenance 展示
- [x] show 能追溯到来源摘要与 session
- [x] wake-up 展示 rule/handoff 来源线索

#### T-16: suggest_rule MCP
- [x] MCP suggest_rule 实现
- [x] 与 confirm/reject 形成完整闭环

#### T-17: scope=project|all
- [x] MCP 查询支持 scope=project|all
- [x] project_name 仅在 scope=project 时必填

### P1 Tasks

#### T-18: ingest cursor
- [x] 每项目 ingest cursor 实现
- [x] 默认增量 ingest
- [x] --full-rescan 作为显式回退

#### T-19: CLI 拆分
- [x] 拆分巨型 CLI 入口到 commands/
- [x] 按命令域拆分

#### T-20: 格式化逻辑复用
- [x] phase formatter 统一
- [x] wake budget formatter 统一
- [x] interactive prompt helpers 统一
- [x] 消灭复制逻辑

#### T-21: adapter 最小契约
- [x] adapter 侧采用最小契约或 registry
- [x] 减少当前耦合
- [x] 不为假设中的未来扩展提前造厚抽象

#### T-22: 性能基线
- [x] ingest 性能基线
- [x] search 性能基线
- [x] wake-up 性能基线

#### T-23: dogfooding
- [x] 用产品自身记录关键学习
- [x] 纳入开发流程

---

## Task Dependencies

```
T-1 (purge) ─────┬─ T-2 (doctor/wake 集成)
                  │
T-3 (统一格式) ───┼─ T-4 (CLI 清晰度)
                  │
T-5 (MCP) ───────┼─ T-6 (输出格式)
                  │
T-7 (HybridSearch) │
                  │
T-8 (CI) ────────┼─ T-9 (类型清理) ── T-10 (测试)
                  │
T-14 (provenance)─┼─ T-15 (provenance 展示)
                  │
T-16 (suggest) ───┼─ T-17 (scope)
                  │
T-18 (cursor) ────┤
                  │
T-19 (CLI 拆分) ──┼─ T-20 (格式化复用)
                  │
T-21 (adapter) ───┤
                  │
T-22 (基线) ──────┤
                  │
T-23 (dogfood) ───┘
```

## Priority Order

### v1.3 实施顺序

1. T-5 (MCP reject_rule_candidate) - 快速完成
2. T-6 (输出格式统一) - 快速完成
3. T-4 (CLI 清晰度改进) - 快速完成
4. T-1 (purge 子命令) - 核心 P0
5. T-2 (doctor/wake 集成) - 依赖 T-1
6. T-3 (状态格式统一) - 依赖 T-4
7. T-7 (HybridSearchLayer) - P1 基础设施
8. T-8-T-13 - P1 稳定性与体验

### v1.4 实施顺序

1. T-14 (provenance 字段) - 核心 P0
2. T-15 (provenance 展示) - 依赖 T-14
3. T-16 (suggest_rule) - 核心 P0
4. T-17 (scope=project|all) - 依赖 T-16
5. T-18 (ingest cursor) - P1 少手动操作
6. T-19-T-21 - P1 可维护性
7. T-22-T-23 - P1 信号与 dogfooding
