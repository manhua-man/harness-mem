# v1x-internal-dogfood-hardening

## Why

`v1x-postship-regressions` 修完了已发布能力的显性回归，但内部试用前检查还暴露出几类“不会立刻炸、却会让自用体验不稳”的边角问题：

1. REST API 在异步请求路径里仍可能触发不安全的 backend 初始化
2. `/search` 默认 `scope=project` 时没有强制 `project_name`，容易造成 project 语义漂移
3. `purge --category structured|all` 对多项目场景不够安全，可能让用户误以为已经清掉 structured memory
4. hybrid search 是可选增强能力，但安装与运行时回退语义需要更明确
5. 本地事件日志已经实现，却没有接到 CLI 主链，无法支撑内部 dogfooding

这次 change 的目标不是扩功能面，而是把 `CLI + MCP + API` 这条内部自用主链收口到“默认安全、语义一致、可观测”。

## What Changes

- 修复 REST API backend 的异步初始化路径，避免在运行中的 event loop 内使用 `asyncio.run()`
- 收紧 `/search` 的 project 语义：`scope=project` 时必须显式给出 `project_name`
- 让 `purge` 支持显式 `-p/--project`，并在 structured/all 场景缺项目上下文时明确失败
- 把 CLI 主链命令、next-step 提示、以及 learning loop 关键动作接入本地 `events.log`
- 把 hybrid search 的可选依赖和回退语义写入安装与接口说明

## Out of Scope

- 新增 Web UI
- 新增 adapter 平台扩张
- 重做 REST API 设计
- 引入远程 telemetry 或外部 analytics
- 解决与这次收口无关的全仓库历史 lint 债
