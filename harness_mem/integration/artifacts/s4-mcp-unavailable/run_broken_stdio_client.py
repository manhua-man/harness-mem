"""Simulate an MCP client against a broken harness-mem launch target (S4 repro)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "harness_mem.mcp.server_missing"],
        env=None,
    )
    try:
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool(
                    "prepare_session_distill",
                    {
                        "project_name": "harness-mem",
                        "client": "auto",
                        "scope": "project",
                        "project_root": str(Path("F:/memory-lab/harness-mem").resolve()),
                        "limit": 10,
                    },
                )
    except Exception as exc:  # noqa: BLE001 — capture client-visible failure
        print(f"CLIENT_EXCEPTION_TYPE: {type(exc).__name__}")
        print(f"CLIENT_EXCEPTION: {exc!r}")
        return 1
    print("UNEXPECTED_SUCCESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
