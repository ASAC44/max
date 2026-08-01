from src.server import mcp, SERVE_SSE


def main():
    # Run the MCP server
    if SERVE_SSE:
        mcp.run(transport="sse")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
