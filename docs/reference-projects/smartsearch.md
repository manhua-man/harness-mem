# smartsearch

- 定位：带 provider 路由、source 抽取和 fallback 的证据检索 CLI；不是 memory
  store，也不是 harness-mem 的联网运行时依赖。
- 上游：本地研究镜像 `F:\\AIInfra\\upstreams\\harness-mem\\smartsearch`。
- 复核基线：`main` 的 `667c465d0f6e`（2026-08-01）。

## 架构与数据流

```text
intent / capability profile
  -> provider search or docs/fetch route
  -> answer text + source extraction
  -> URL/source deduplication
  -> fallback/degraded/failed result
```

路由层根据 provider capability 选择 search、fetch 或 docs 路径；source parser 接受
inline、heading 和 function-call 形式的来源，再将答案文本与来源记录分离。主 provider
失败但 fallback 成功时，结果保留 degraded 轨迹；最低能力 profile 不满足时 fail closed。

## 状态与错误语义

- `answered`：答案和来源均可追溯。
- `degraded`：发生 fallback，但仍获得可用来源；不能伪装成主路径成功。
- `failed`：没有可接受 provider/fetch 结果。
- source URL 去重是结果结构的一部分，不是 UI 装饰。

## 可复核证据

| 主题 | 本地源码证据 | 结论 |
|---|---|---|
| Source parser | `F:\\AIInfra\\upstreams\\harness-mem\\smartsearch\\src\\smart_search\\sources.py:123-171,320-429` | 统一抽取并去重 source。 |
| Fallback/degraded | `F:\\AIInfra\\upstreams\\harness-mem\\smartsearch\\tests\\test_smoke.py`；`tests\\test_service.py` | fallback 成功与硬失败可区分。 |
| Capability fail-closed | `F:\\AIInfra\\upstreams\\harness-mem\\smartsearch\\tests\\test_service.py` | 能力缺失不能静默降级成可信答案。 |

## 对 harness-mem：adopt / adapt / reject

**Adopt**：在现有 provenance/retrieval signal 上增加稳定的 evidence-attempt trace，
把 `answered`、`abstained:no_evidence`、`degraded`、`failed` 作为可查询结果语义。

**Adapt**：只在 Skill/CLI 证据辅助路径使用；不让外部联网 source 直接写入 Memory、Rule
或 candidate truth。

**Reject**：provider keys、联网搜索、多 provider 配置进入默认 MCP/runtime；这会改变
本地优先和隐私边界。

## 影响版本

`0.9.9` 将其 fallback/source trace 经验用于七宿主 replay 和完整检索结果审计。验收
要求 fallback 轨迹、source ID、过滤理由和失败审计行都可重放，且失败不会生成可信长期事实。
