import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check_protocol():
    root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(root / "main.py")],
        cwd=root,
        env=os.environ.copy(),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert len(tools.tools) == 16
            print("MCP stdio handshake OK; 16 tools listed")


async def main():
    with anyio.fail_after(10):
        await check_protocol()


if __name__ == "__main__":
    anyio.run(main)
