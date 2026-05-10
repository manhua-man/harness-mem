# Distillation Rules

> Synced from the repo-local session-distill shared template.
> Edit `scripts/ai/session-distill/templates/distillation-rules.template.md` and rerun `python scripts/ai/session-distill/sync_references.py` from the repo root.

## 这份文件解决什么问题

在把任何东西往 `knowledge-base.md`、项目规则、模块文档继续上提之前，先读这份规则。

它用于判断：

- 什么只该留在 session note
- 什么值得进入 `knowledge-base.md`
- 什么应该变成 repo 级默认行为
- 什么本质上是系统事实，应该回到文档、注释或测试

## 先分类，再决定 promote

默认顺序：

1. 先判断它是在描述 AI 默认动作，还是系统真相
2. 再判断它的适用范围是任务内、跨会话，还是 repo 级默认值
3. 最后才问“要不要 promote”

不要一上来就问“这条要不要升”。

## 目标层级

- `distilled/sessions/<session-id>.md`
  - 任务内证据
  - 临时路径、参数、主机、workaround
  - 失败尝试和决策历史
- `knowledge-base.md`
  - 可复用 workflow
  - 命令组合
  - 文件地图
  - 排障切入点
  - 失败模式和自动化候选
- 项目规则
  - 会改变未来 AI 默认行为的规则
  - 安全门、review 默认动作、工程纪律、协作顺序
- 模块文档 / 注释 / 测试
  - 接口语义
  - 状态流转
  - 字段真值
  - 业务限制
  - 非显而易见但属于系统层的代码逻辑

判断捷径：

- 能写成“AI 以后默认应该 ...” -> 考虑项目规则
- 能写成“这个模块 / 系统本来就是这样工作” -> 优先文档、注释或测试

## 值得 promote 的内容

- 稳定且跨会话可复用的 workflow
- 真正解决问题的命令模式
- 能明显缩短定位路径的文件地图
- 可操作、可复用的 failure pattern
- 已经出现重复迹象的自动化机会

## 只留在 session note 的内容

- 一次性参数、ID、时间戳、主机信息
- 只在当前任务有效的调试残留
- 有历史价值但没有复用价值的探索记录

## 直接当噪声过滤

- 客户端或 IDE 注入的包装块，只要不影响结论就直接过滤
- 大段工具输出原文，只保留其中真正可复用的命令、文件地图或失败模式
- request id、重试噪声、重复 commentary 更新
- 纯临时的分支名、时间、tab 状态、窗口状态，除非后续规则明确依赖它
- `<ide_opened_file>`、`<local-command-caveat>`、`<turn_aborted>` 这类无决策价值的注入文本
- claude-mem 查询失败本身，不要当成知识结论

## Promotion Checklist

往 session note 之上提升前，通常至少满足其中大部分：

- recurrence：以后大概率还会遇到
- leverage：会改变未来分析、实现或 review 路径
- hiddenness：不是看代码表面就能直接知道
- novelty：repo 现有规则、文档、测试还没清晰写出来
- normalization：能被改写成短而稳定的规则或事实
- evidence：至少有一个真实 session 支撑
- dedupe：可以并进已有知识，而不是制造第二种说法

## 常见误判

“经常遇到而且不明显”的业务逻辑，依然不自动等于项目规则。

例子：

- “以后遇到 DTO 行为，AI 默认先核对 transform + validation contract” -> 项目规则
- “这个上报链路是先预检查，再正式上报” -> 模块事实

## 落点提示

- `AGENTS.md` / `CLAUDE.md`
  - repo 级协作默认值
- `.kiro/steering/generalbeliefs.md`
  - 工程纪律、发版/回滚策略、review heuristics、跨模块默认动作
- `.kiro/steering/typeserver.md`
  - TypeScript、NestJS、DTO、transform、validation、Jest、测试形状相关规则
- 模块文档 / 测试 / 注释
  - 模块局部契约和系统行为

## 默认拍板方式

- 目标层级明确：直接写到对应位置
- 明显属于模块事实：不要升成项目规则
- 落点不明确：先记成 `promotion candidate`，附一句理由和建议落点
- 会改 repo 级默认行为但影响面还模糊：停下来让用户拍板
