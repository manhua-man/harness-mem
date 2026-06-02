# docs/

`harness-mem` 的产品文档入口。

| 目录 | 内容 |
|---|---|
| `benchmark/` | benchmark 系统设计与各版本基线，例如 `v160-baseline.md`、`v161-bucket-budget-impact.md`、`longmemeval-five-dimensions.md` |
| `roadmap/` | 版本规划与 roadmap proposal |

其中 LongMemEval / embedding 相关文档默认以 `all-MiniLM-L6-v2` 作为基线锚点，除非某份 shootout 文档明确写了其它模型。

根目录常驻文档：

| 文件 | 用途 |
|---|---|
| `best-practices.md` | 日常使用最佳实践 |
| `cli-design-expert.md` | CLI 设计说明 |
| `error-codes.md` | `doctor` 输出的 `HM-xxx` 错误码与修复命令映射 |
| `reference-projects.md` | 外部 memory/wiki/self-evolution 参考项目，以及本地 `F:\memory-lab\upstreams` 镜像说明 |
| `retrospective-v13-v14.md` | v13 -> v14 架构演进评审记录 |
| `roadmap-status.md` | 当前 roadmap 完成情况：从 v1.6 到 v2.9 的已完成项、边界和未做项 |
| `roadmap-v15x.md` | v1.5.x 分切片交付记录（v1.5.1 - v1.5.3） |
| `roadmap-v16x.md` | v1.6.x roadmap：measurement foundation、typing、bucket budget、persistent vectors |
| `roadmap-v17x.md` | v1.7.x roadmap：temporal schema、supersede、bounded relation graph、verbatim exact evidence search |
| `roadmap-v22x.md` | v2.2.x roadmap：AI IDE 入口闭环、跨客户端测试、auto-review UX |
| `roadmap-v23.md` | v2.3 roadmap：Signals / Replay 地基、`RetrievalSignal`、`MetabolismRun`、`metabolism_preview` |
| `roadmap-v24.md` | v2.4 roadmap：host-triggered reflection、job queue、health / doctor 韧性 |
| `roadmap-v25.md` | v2.5 roadmap：context assembly、Memory Stack renderer、file-context |
| `roadmap-v26.md` | v2.6 roadmap：wiki bridge、compact claim index、contradiction suggestions、compact wake renderer |
| `roadmap-v27.md` | v2.7 roadmap：cross-project skills、controlled activation、skill improvement suggestions |
| `roadmap-v28.md` | v2.8 roadmap：session-distill maintenance、knowledge-base review/prune/verify surfaces |
| `roadmap-v29.md` | v2.9 roadmap：PRD sync candidate surface |
| `roadmap-vision-v16-v18.md` | v1.6 - v1.8 远景方向，不等同于承诺路线图 |

设计规格在 `openspec/specs/` 和 `openspec/changes/`。
工作流 skill 资产在 `tools/`。
插件与集成文档在 `plugins/harness-mem/`。
