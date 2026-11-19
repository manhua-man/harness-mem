# 宿主接入与诊断

手工整理和查询使用 [MCP 接入](mcp-setup.md)。希望宿主在会话开始、结束等时机调用记忆系统时，再安装生命周期 Hook。以 Codex 为例，在已安装运行包的环境中执行：

```sh
harness-mem quickstart --client codex
```

这会写用户级 Hook 配置，保留已有后台授权状态。按输出到 Codex 的 Hooks 设置中审阅并信任配置，然后开始新任务。若明确要允许后台模型处理，可使用 `harness-mem quickstart --client codex --confirm`。该授权作用于用户级配置，显式项目策略优先。

`harness-mem doctor` 用来检查运行环境，`harness-mem integration hooks --help` 可查看 Hook 管理能力。安装后的可用性要在相应宿主中验证：MCP 用工具列表和实际调用检查，Hook 用新会话触发和对应任务结果检查。
