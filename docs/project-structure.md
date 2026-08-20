## harness-mem 仓库结构（整合后阅读视图）

这个仓库已经按职能分了“代码组 / 文档组 / 运行时组 / 元数据组”。
运行时真值（`harness_mem/`）保留在仓库根；其余交付资产已完成物理收敛到 `code/`（`crates`、`tests`、`scripts`、`tools`、`plugins`、`mcps`）。

### 1) 代码与执行实现

- `harness_mem/`
  Python runtime（CLI、MCP、distill 骨干、验证、检索、Hook、存储）。

- `code/crates/`
  Rust 核心扩展（`harness_mem_core_rs`）与构建产物配置。

- `code/plugins/`
  Agent 客户端侧接入资产（命令、模板、集成声明）。

- `code/tools/`
  可执行指令/调试技能（例如 `hm-distill`），不承载主运行时核心逻辑。

- `code/mcps/`
  MCP 配置、声明与调试支撑项。

- `code/scripts/`
  构建脚本、发布前检查脚本、仓库维护脚本。

- `code/tests/`
  单测/合约/验收/质量门禁。

- `docs/canvases/`
  视觉化设计和架构快照。当前仅作文档/审计资产，不是运行时依赖。

### 2) 文档与合约

- `docs/`
  架构合同、阶段模型、验收计划、规范变更历史。

- 根目录文档
  `README.md`、`README.zh-CN.md`、`CHANGELOG.md`、`DESIGN.md`、`AGENTS.md`、`CLAUDE.md`、`ROADMAP` 系列说明、`.github/`。

- `docs/canvases/`
  架构/演进快照与可视化图谱（偏文档资产）。

### 3) 运行时数据与工作区元数据（本地产物）

- `.codex/`、`.claude/`、`.cursor/`、`.grok/`、`.opencode/`、`.gstack/`
  - 宿主命令、技能、工作流、局部历史与协作痕迹（与你会话相关，不是仓库源码）。

- `.harness-mem/`、`.hypothesis/`、`.local-archive/`
  - 运行时配置/数据缓存/本地临时归档。

- `.venv/`
  - 本地 Python 环境（按项目隔离，不是源码）。

- `.agents/`、`LICENSE`、`SECURITY.md`、`.gitattributes`、`.gitignore`
  - 协作规则、许可证与仓库元信息。

### 4) 物理迁移状态

已完成迁移，现状如下：

- 运行时主干 `harness_mem/` 未移动。
- 非主干代码资产已收敛到 `code/`，并同步更新 `Cargo.toml`、`pyproject.toml`、
  `code/scripts/ensure_mcps_canonical.py`、`code/tools/outcome-verifier/scripts/verify_outcomes.py`
  等路径引用。
- 旧根目录（`crates/`、`plugins/`、`tests/`、`scripts/`、`tools/`、`mcps/`）不再存在；
  读写与文档入口统一迁移到 `code/...`。

### 5) 推荐入口（已收敛）

- 开发：`harness_mem/`（运行时）、`code/tools/`（指令）、`code/tests/`（测试）
- 结构速览：`.\code\scripts\show-project-layout.ps1`

### 清洁脚本（按你刚才提的两档）

```powershell
.\code\scripts\clean-workspace.ps1 clean      # 清理临时缓存：.tmp/.temp/terminals/.hypothesis + 各类 __pycache__/.mypy_cache/.pytest_cache/.ruff_cache/.coverage
.\code\scripts\clean-workspace.ps1 clean-all  # 在 clean 基础上再清理构建产物：dist/build/target/node_modules/eggs/site/.tox/.next
```
