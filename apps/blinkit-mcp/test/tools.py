import sys
import os
import asyncio
import json
from pathlib import Path

# Add project root to Python path to allow importing from src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.server import mcp


async def list_tools():
    # FastMCP stores tools in a list or registry.
    # Current version uses decorators to register.
    # We can inspect the underlying list_tools capability.

    # We can use the server's list_tools method directly if exposed,
    # or iterate over the internal registry.

    print("Verifying registered tools...")
    tools = await mcp.list_tools()
    for tool in tools:
        print(f"- {tool.name}: {tool.description}")

    manifest = json.loads(Path("manifest.json").read_text())
    assert {tool.name for tool in tools} == {
        tool["name"] for tool in manifest["tools"]
    }
    print("Manifest matches registered tools.")


if __name__ == "__main__":
    asyncio.run(list_tools())
