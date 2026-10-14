# hm 入口来源与恢复

核对日期：2026-10-07。本文件说明客户端入口归谁维护；行为以仓库源码和生成器为准。

`hm` 由 [harness-mem GitHub 仓库](https://github.com/manhua-man/harness-mem) 维护。本机工作树在 `F:/AIInfra/harness-mem`；本地未提交内容不等同于 GitHub 已发布内容。

| 内容 | 维护位置 |
| --- | --- |
| 入口行为源文件 | `code/plugins/harness-mem/commands/hm/hm.md` |
| 客户端格式生成与安装 | `harness_mem/integration/command_sync.py` |
| wire 版本真值 | `harness_mem/version.py` |
| 项目内入口镜像同步 | `code/scripts/sync_hm_mirrors.py` |

Codex 使用 `~/.codex/skills/hm/SKILL.md`，Cursor 使用 `~/.cursor/skills/hm/SKILL.md`；两者都是项目生成的客户端入口。更新行为时先改仓库源文件，再同步镜像与客户端。不要单独手改生成的 `SKILL.md` 或把它迁到 OneDrive 作为另一份维护源。当前只有一个日常入口 `hm`；七个旧 `hm-*` 入口已退役。

在已取得目标仓库版本、Python 环境可导入该版本的 `harness_mem` 后，从仓库根目录同步：

```powershell
python code/scripts/sync_hm_mirrors.py
python code/scripts/sync_hm_mirrors.py --check
python -m harness_mem.cli integration commands sync --client codex --dry-run
python -m harness_mem.cli integration commands sync --client cursor --dry-run
python -m harness_mem.cli integration commands sync --client codex
python -m harness_mem.cli integration commands sync --client cursor
```

上述客户端同步只管理入口文本，并清除准确匹配的旧入口。它不安装 MCP 连接、不修复 Hook，也不读写真实记忆。若当前 Agent 尚未连接 harness-mem，应在 Agent 或 Router 中连接后再使用 `hm`。

换机时从 GitHub 克隆目标版本，按仓库 README 安装，再生成当前客户端入口；预编译包来自 [GitHub Releases](https://github.com/manhua-man/harness-mem/releases)，不从旧文档中的 PyPI 链接恢复。

OneDrive 的 `AI配置` 只保留来源说明和恢复索引。该目录中的 `hm-source.md` 与客户端旁的 `SOURCE.md` 是本说明的阅读副本，不包含另一套技能实现。实际 OneDrive 根路径从本机配置确认，不沿用历史机器的盘符。

本次核对的 wire 为 `hm-wire-v3.5`，它不是 Python 包版本。入口同步与文本一致性通过，不表示真实 MCP、Hook 或记忆运行链已验证。
