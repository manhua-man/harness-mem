# AGENTS.md · 项目事实

Python 包版本以 [pyproject.toml](pyproject.toml) 为准。Python 实现位于 `harness_mem/`，Maturin 构建的 PyO3 扩展位于 [code/crates/harness_mem_core_rs](code/crates/harness_mem_core_rs)。扩展有自己的 crate 版本。

## 从用户入口定位实现

| 入口 | 负责的行为 | 实现 |
| --- | --- | --- |
| `harness-mem-mcp` | 通过 stdio 提供记忆工具 | [服务](harness_mem/mcp/server.py)、[工具规格](harness_mem/mcp/tool_specs.py)、[处理器绑定](harness_mem/mcp/tool_handlers.py) |
| `harness-mem` | 配置、诊断、宿主接入、维护 | [CLI](harness_mem/cli.py) |
| `harness-mem-hook` | 接收宿主生命周期事件 | [Hook 入口](harness_mem/host_entry/__main__.py) |

- **Distill** 的来源适配位于 [adapters](harness_mem/adapters)，手工任务的选择、冻结与恢复位于 [manual_distill.py](harness_mem/commands/manual_distill.py)，提交与收尾从 [distill_handlers.py](harness_mem/mcp/distill_handlers.py) 追踪。
- **Search** 的范围、分页和结果形态由 [read_search_handlers.py](harness_mem/mcp/read_search_handlers.py) 处理。当前知识读取、匹配和排序集中在 [read_knowledge.py](harness_mem/read_knowledge.py)。Wake 从 [read_wake_handlers.py](harness_mem/mcp/read_wake_handlers.py) 调用同一读取层。
- SQLite 中的 `knowledge_entries` 保存当前知识。原生会话、任务处理材料和查询反馈各有独立用途。修改存储时先从 [storage](harness_mem/storage) 核对读者、事务和作用域。
- [插件清单](code/plugins/harness-mem/.codex-plugin/plugin.json) 与 [MCP 配置](code/plugins/harness-mem/.mcp.json) 负责插件接入。业务操作使用公开工具。仓内维护脚本在 [code/scripts](code/scripts)，结果探针在 [qualification](harness_mem/qualification)。

## 构建和验证

在仓库根目录、已激活的开发环境中运行：

```sh
python -m pip install ".[dev]"
python code/scripts/ensure_mcps_canonical.py
python -m pytest -q code/tests/test_mcp_public_surface_contract.py code/tests/test_mcp_console_script.py
python -m pytest -q code/tests/test_manual_session_flow.py code/tests/test_global_memory_defaults.py
cargo test --workspace
```

描述文件脚本会重新生成 [20 份公开工具规格](code/mcps/harness_mem/tools)，运行后检查 Git 差异。完整 CI 的触发条件和命令见 [public-smoke.yml](.github/workflows/public-smoke.yml)。[结果合同](.codex/outcomes.json) 列出独立探针。

## 文档导航

[README](README.md) 是使用入口和功能索引。[CLAUDE.md](CLAUDE.md) 约定如何协作，[DESIGN.md](DESIGN.md) 约定 CLI 和 Agent 如何向用户呈现结果。协议文档结构参考外部 [harness-coding-protocol](https://github.com/manhua-man/harness-coding-protocol/tree/37af1c748495a2a9a37e581c246506d43e79da9a)。
