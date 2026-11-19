# 连接记忆服务

先按 [源码安装说明](../README.md) 安装到目标 Python 环境。在支持 stdio 的 MCP 客户端中添加一个服务。使用 `mcpServers` 配置格式的客户端可使用：

```json
{
  "mcpServers": {
    "harness_mem": {
      "command": "harness-mem-mcp",
      "args": []
    }
  }
}
```

客户端找不到命令时，把 `command` 换成该虚拟环境中可执行文件的绝对路径。Windows 通常位于环境的 `Scripts/harness-mem-mcp.exe`，Linux 和 macOS 通常位于 `bin/harness-mem-mcp`。

重新加载客户端后查看工具列表。调用 `inspect_sessions({})` 盘点可读取的历史，或调用 `search_memory({"query":"之前约定的验证方式是什么？"})` 检索已有知识。即使知识库为空，成功连接后仍能列出工具。插件使用的配置可以直接核对。[插件 MCP 配置](../code/plugins/harness-mem/.mcp.json)
