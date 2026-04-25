# v1x-internal-dogfood-hardening Tasks

## API 收口

- [x] 为 API backend 增加 async-safe 初始化路径
- [x] 让 `/search` 在 `scope=project` 时强制要求 `project_name`
- [x] 在 `/search` 返回 `requested_mode`、`effective_mode`、`fallback_reason`
- [x] 补 API 回归测试，覆盖 project scope 校验和 mode 回显

## CLI / Purge 收口

- [x] 为 `purge` 增加 `-p/--project`
- [x] 在 `structured` / `all` purge 缺项目上下文时明确失败，而不是静默跳过
- [x] 让 doctor / status / wake-up 的 purge 建议带上项目上下文
- [x] 补 CLI 回归测试，覆盖 project-scoped purge 行为

## 本地事件日志

- [x] 把 CLI 主链命令接到本地 `events.log`
- [x] 记录 next-step 展示、next-step 采用、以及 learning loop 关键动作
- [x] 修复测试环境下 `get_event_logger()` 的 data-dir 复用问题
- [x] 补测试，验证关键命令会落本地事件

## 开发工具入口收口

- [x] 移除测试文件里的 `sys.path` bootstrap，恢复正常包导入
- [x] 把 LongMemEval 入口迁到 `python -m harness_mem.tools.longmemeval`
- [x] 把 e2e smoke 入口迁到 `python -m harness_mem.tools.e2e`
- [x] 同步 benchmark 文档里的正式运行命令

## Validation

- [x] `python -m pytest tests/test_api.py tests/test_cli_ux.py -q`
- [x] `python -m pytest -q`
- [x] `python -m mypy harness_mem`
- [x] `python -m ruff check harness_mem tests`
