# S4 MCP unavailable — Cursor agent transcript (isolated broken launch)

Clients: Cursor (simulated daily workflow; MCP stdio client against broken launch target)
harness-mem version: local checkout (`<REPO_ROOT>`)
Project: `harness-mem` (`project_root=F:/memory-lab/harness-mem`)
Environment: Windows; harness-mem MCP launch intentionally broken for this run only

## Temporary MCP config (do not leave enabled)

File used for repro (copy to a **separate** Cursor workspace `.cursor/mcp.json` only for this test):

`harness_mem/integration/artifacts/s4-mcp-unavailable/mcp.json.broken-s4-test`

```json
{
  "mcpServers": {
    "harness_mem_s4_broken": {
      "command": "python",
      "args": ["-m", "harness_mem.mcp.server_missing"]
    }
  }
}
```

Restore after test: remove that workspace override or revert to normal `harness_mem.mcp.server` / `user-mcp-router` setup.

Boundary for **this** workspace session: live Cursor still had `user-mcp-router` connected, so a control call to `prepare_session_distill` via the router **succeeded** during the same window. The transcript below models the **broken direct stdio server** path required by S4, using `run_broken_stdio_client.py` output as the tool failure the agent would see after MCP reload with only the broken server.

---

## Transcript

**User**

用 harness-mem 整理最近 session

**Assistant** (tool attempt)

Calling MCP `prepare_session_distill` with:

- `project_name`: `harness-mem`
- `client`: `auto`
- `scope`: `project`
- `project_root`: `F:/memory-lab/harness-mem`
- `limit`: `10`

**Tool / transport result (failed)**

```
CLIENT_EXCEPTION_TYPE: ExceptionGroup
CLIENT_EXCEPTION: ExceptionGroup('unhandled errors in a TaskGroup', [ExceptionGroup('unhandled errors in a TaskGroup', [McpError('Connection closed')])])

Server subprocess stderr (launch target):
C:\Users\ManHua\.local\python313\python.exe: No module named harness_mem.mcp.server_missing
```

Subprocess repro (initialize, no JSON-RPC handshake):

- return code: `1`
- stdout: empty
- stderr: `No module named harness_mem.mcp.server_missing`

**Assistant** (user-facing)

harness-mem **MCP runtime unavailable**：当前客户端连不上 harness-mem 的 MCP 服务（子进程在握手前退出，`Connection closed` / 启动模块不存在）。因此无法执行「整理最近 session」所需的 `prepare_session_distill` → session-distill → `auto_review_candidates` 闭环。

这不是「没有新 session」或「没有 LLM」——是 **transport / 启动配置** 问题。

**建议你这边（维护者 / 本机排障）**

1. 检查 Cursor（或该测试客户端）里 harness-mem MCP 的启动命令是否仍为
   `python -m harness_mem.mcp.server`（不要指向 `server_missing` 等错误模块）。
2. 在本机运行 **`harness-mem doctor`**，查看数据目录、项目上下文与 MCP 相关自检结果（CLI 仅作诊断，不是日常用户路径）。

**我不会做的**

- 不会让你改用已移除的日常 CLI：`harness-mem distill` / `wake` / `search` / `timeline` / `candidates` 来完成这次整理。
- 不会在 MCP 不可用时用正则、git log 或文件扫描假装 distill 出候选。

MCP 恢复后，你可以再说一次「用 harness-mem 整理最近 session」，我会走正常 MCP + session-distill 流程。

---

## Pass criteria check (this transcript)

| Criterion | Result |
|-----------|--------|
| MCP 不可用 / 调用失败明确可见 | Yes (`Connection closed`, module missing, no handshake) |
| 含 `harness-mem doctor` 指引 | Yes |
| 未教用户跑旧 daily CLI (`harness-mem distill` 等) | Yes (explicit negation) |
| 完整 client UI 录屏级 transcript | Partial — tool failure from stdio client script + agent wording; not a separate Cursor window recording |

## Artifacts

- `run_broken_stdio_client.py` — MCP Python client against broken launch
- `mcp.json.broken-s4-test` — broken config snippet for isolated workspace test
