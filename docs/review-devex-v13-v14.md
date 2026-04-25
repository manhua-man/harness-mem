# DevEx 评审：harness-mem v1.2.0 → v1.3/v1.4

## 1. 安装和入门体验

**当前状态：良**

`pip install -e . && harness-mem quickstart` 链路是通顺的。CLI 设计准则（默认优先、状态感知、渐进披露）在 README 里贯彻得很好。

**风险点：**

- **仅 `pip install -e .`（editable install）** — 没有提供 `pip install harness-mem` 的 PyPI 发布流程。新用户必须 clone 仓库。v1.3 应考虑至少打包到 PyPI/test-PyPI。
- **跨平台：** SQLite FTS5 在 Windows/Mac/Linux 上行为一致，无平台锁定。但代码中硬编码了 `Path.home() / ".claude" / "projects"` 作为 Claude Code session 目录，这在 Windows 上正确（`~/.claude` 映射到 `C:\Users\xxx\.claude`），但未做防御性检查——如果用户改了 Claude Code 的项目目录就会静默失败。
- **依赖：** 仅 `pydantic>=2.0` 和 `sqlite-utils>=3.35`，非常轻量。这是优点，但也意味着没有 lockfile，不同时间安装可能拿到不同的传递依赖。

**建议：** v1.3 优先级——完成 PyPI 发布脚本（`flit build && twine upload`），README 加 PyPI badge。

## 2. 测试覆盖和可测试性

**当前状态：中上**

代码约 3865 行，测试约 1015 行（`test_cli_ux.py` 504 + `test_cli_flows.py` 172 + `test_distill_and_search.py` 339），覆盖率约 26%。核心模块（`cli_commands.py` 236 行）基本被覆盖。

**亮点：**
- 测试使用 `tmp_path` + `monkeypatch` 替换 `DEFAULT_DATA_DIR`，无外部依赖，可并行运行
- `test_cli_ux.py` 覆盖了 quickstart/doctor/wake/profile 的多个分支
- `test_distill_and_search.py` 覆盖了双层检索 + category 过滤

**缺口：**
- **无 storage 层单元测试**：`local_structured_store.py`（350 行）、`sqlite_index.py`（361 行）只有端到端覆盖，没有独立的 SQL 查询测试
- **adapter 层无 mock 测试**：`ClaudeCodeAdapter`（324 行）直接读文件系统，没有对文件不存在/格式损坏/超大文件的隔离测试
- **MCP server 无测试**（即使只是 smoke test）：`mcp/server.py` 没有被任何测试文件 import
- **无压力/性能测试**：ingest 大量 session 时没有基准
- **无 Windows 专用 CI**：`pathlib` 虽然是跨平台的，但 `os.dup2()` 在 MCP server 启动时的使用在 Windows 上可能有问题

**建议：** v1.3 应优先补齐 storage layer 单元测试 + adapter 隔离测试，尤其是 SQLite FTS5 的边界查询。

## 3. 贡献/扩展体验

**当前状态：中**

**新增 adapter：**
- 需要实现 `MemoryBackend` protocol（`core/interfaces/memory_backend.py`），这是好的抽象
- 但当前 `ClaudeCodeAdapter` 和 `CodexAdapter` 之间没有共享基类或 adapter protocol
- 新增 adapter 还需在 `cli.py` 的 import/ingest 分支里追加条件判断——这是耦合点

**代码组织：**
```
harness_mem/
  adapters/claude_code/        # Claude Code 专用
  adapters/codex/              # Codex 专用
  core/interfaces/             # Protocol 定义（好！）
  core/schemas/                # Pydantic 模型
  storage/                     # 存储实现
  cli.py                       # 1242 行（太大）
  cli_commands.py              # 236 行（适度）
  mcp/server.py                # MCP 适配器
```

`cli.py` 1242 行是明显的瓶颈。所有命令的实现和参数解析挤在一个文件里。`cli_commands.py` 只取了 `correct/confirm/reject/handoff`，其他命令的逻辑仍然嵌在 `cli.py` 内。

**建议：** v1.4 应拆分 `cli.py` 为按子命令分组的模块（如 `commands/ingest.py`、`commands/doctor.py`...）。新增 adapter 时应提供一个 `BaseAdapter` 基类或至少一个 protocol 做契约检查。

## 4. 错误处理

**当前状态：中**

**好的方面：**
- doctor 和 quickstart 对"无数据"状态提供了明确的下一步建议
- `_resolve_project_name` 在没有 project 时 fallback 到环境变量 → active project → 交互式提示
- MCP server 有 stdout -> stderr 重定向保护

**问题：**
- **错误信息缺乏上下文**：`cmd_correct` 找不到 session 时只打印 `No observations found for session: {id}`，没有说去 `harness-mem ingest`。初次用户可能卡住。
- **文件系统异常隐式消化**：如果 `.claude/projects/{project}` 目录不存在或权限不够，adapter 返回空列表而非给出警告。
- **SQLite 错误盲区**：`sqlite_index.py` 中 FTS5 查询失败（如语法错误的 query）会抛出原始 `sqlite3.OperationalError`，没有翻译成用户友好的消息。
- **无退出码文档**：用户无法从脚本上判断 0/1 的含义。

**建议：** v1.3 加入全局异常钩子包装 SQLite 错误；adapter 在目录不存在时打印 warning 而不是静默跳过。

## 5. v1.3/v1.4 DevEx 优先事项排名

| 优先级 | 事项 | 阶段 | 理由 |
|--------|------|------|------|
| P0 | PyPI 发布 + README 加安装 badge | v1.3 | 降低首次接触门槛 |
| P0 | Storage layer 单元测试 | v1.3 | SQLite 是核心依赖，测试空白风险高 |
| P1 | `cli.py` 按命令模块拆分 | v1.4 | 1242 行已到维护临界点 |
| P1 | adapter protocol 统一 + BaseAdapter | v1.4 | 降低扩展阻力 |
| P2 | SQLite 错误翻译 + adapter 目录存在性检查 | v1.3 | 小改动但消除几类困惑场景 |
| P2 | MCP server smoke test | v1.3 | 当前 0 覆盖 |
| P3 | 性能基准（大量 session ingest） | v1.4 | 当前无数据 |
