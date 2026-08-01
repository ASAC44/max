#!/bin/bash

# CRITICAL: This script's stdout is the MCP JSON-RPC protocol channel.
# ALL non-JSON output MUST go to stderr. We redirect fd1 to fd2 for the
# entire setup phase, then restore it only for the final exec.
exec 3>&1          # save original stdout (MCP protocol channel) to fd3
exec 1>&2          # redirect ALL stdout to stderr for setup phase

# Add common install locations for uv to PATH
export PATH=$HOME/.local/bin:$HOME/.cargo/bin:$PATH

# Ensure we are in the script's directory
cd "$(dirname "$0")"

# detailed logging for debugging if it still fails
if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Re-add to PATH in case it wasn't there before (redundant but safe)
    export PATH=$HOME/.local/bin:$HOME/.cargo/bin:$PATH
else
    echo "uv found at: $(command -v uv)"
fi

# Ensure dependencies are installed (must complete before server can start)
echo "Syncing dependencies..."
uv sync --frozen

# Always ensure the correct Firefox version is installed for the current Playwright.
# We cannot cache-check by directory name because a Playwright upgrade changes
# the required browser build number (e.g. firefox-1497 vs firefox-1509).
# Run in background so the MCP server starts immediately and can respond to
# Claude Desktop's initialize handshake without timing out.
INSTALL_MARKER="$HOME/.blinkit_mcp/.playwright_installing"
INSTALL_DONE_MARKER="$HOME/.blinkit_mcp/.playwright_ready"
mkdir -p "$HOME/.blinkit_mcp"
rm -f "$INSTALL_DONE_MARKER"

echo "Ensuring Playwright Firefox is installed (background)..."
(
    touch "$INSTALL_MARKER"
    uv run playwright install firefox 2>&1
    rm -f "$INSTALL_MARKER"
    touch "$INSTALL_DONE_MARKER"
    echo "Playwright Firefox install complete."
) &

# Restore stdout to the MCP protocol channel and launch the server
echo "Starting Blinkit MCP..."
exec 1>&3 3>&-     # restore fd1 from fd3, close fd3
exec uv run main.py
