# AGENTS.md · 项目事实

harness-mem 给宿主 Agent 提供两项本地能力。项目版本与构建依赖见 [pyproject.toml](pyproject.toml)。宿主读取两份 Skill，并在能导入本包的 Python 环境中执行操作。

| 用户意图 | 宿主入口 | Python 入口 |
| --- | --- | --- |
| 整理完结对话、继续中断的阅读 | [Distill Skill](.agents/skills/distill/SKILL.md) | [Distill](harness_mem/distill.py) |
| 找回当前知识、回答问题 | [Search Skill](.agents/skills/search/SKILL.md) | [search](harness_mem/search/__init__.py) |

## 运行时归属

- [会话适配](harness_mem/adapters) 负责读取宿主来源。[手工批次](harness_mem/commands/manual_distill.py) 冻结来源版本，绑定任务和已处理的进度。当前 Agent 给出判断，[证据核验](harness_mem/commands/evidence_admission.py) 和 [知识吸收](harness_mem/commands/separated_assimilation.py) 负责保存前的检查。
- [当前知识检索](harness_mem/read_knowledge.py) 读取 SQLite 当前知识、排序并归并重复结果。[本地操作绑定](harness_mem/agent_runtime.py) 管理每次调用的数据库与关闭时机。生产默认数据根由 [LocalMemoryBackend](harness_mem/storage/local_memory_backend.py) 决定；验收时指定隔离目录。
- [原生扩展](code/crates/harness_mem_core_rs) 由 Maturin 构建。后台执行、历史维护和宿主 Hook 另有内部代码。上述两份 Skill 直接使用本地运行时。

## 开发和部署

在仓库根目录和目标 Python 虚拟环境中，维护者可用 `python -m pip install ".[dev]"` 安装本地源码和开发依赖；从源码构建需要 Rust 与平台编译工具链。宿主需要同时能发现 Skill 和导入 Python 包。wheel 与 sdist 随包携带两份 Skill，宿主的 Skill 搜索路径按实际集成配置。

运行 `python -m pytest -q code/tests/test_agent_manual_distill.py code/tests/test_global_memory_defaults.py` 检查手工整理与全项目检索。[CI](.github/workflows/public-smoke.yml) 记录构建与回归命令，[结果合同](.codex/outcomes.json) 维护运行探针。用户步骤见 [README](README.md)，协作与体验约定见 [CLAUDE.md](CLAUDE.md) 和 [DESIGN.md](DESIGN.md)。
