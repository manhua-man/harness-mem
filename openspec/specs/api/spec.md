# api Specification

## Purpose

> **Removed in v2.1.** REST API 层（`harness-mem api`、`/search` 端点、`harness_mem.api` 包）已从产品 surface 与依赖清单中移除。本文件保留为历史标记，不再承诺任何 API 行为。MCP 是当前唯一受支持的 runtime 接入面。

如果需要程序化访问 harness-mem 数据，请通过：

- **MCP 工具**：`search_memory`、`timeline`、`get_observations`、`get_confirmed_rules` 等。
- **本地数据目录**：`~/.harness-mem/data/` 下的 JSON blob 与 SQLite FTS5 索引（仅在 maintenance 场景使用，不作为稳定接口）。

## Requirements

无。本规格不再提出 REST 接口契约。

历史变更见 `openspec/changes/v1x-internal-dogfood-hardening/`、`openspec/changes/v15x-retrieval-coordinator/` 等档案；它们记录的是 v2.1 之前的 REST 实现，不代表当前代码库行为。
