"""Safe-mode entry point for the Engram MCP server.

Sets ENGRAM_SAFE_MODE before the server module is imported, so the
consultation tools (which can call external LLM providers and read API keys)
are never registered. Point agents that should have memory without network +
credential access at the `engram-mcp-safe` console script instead of
`engram-mcp`.

Equivalent to running `engram-mcp` with ENGRAM_SAFE_MODE=1 in the environment.
"""

import os


def main() -> None:
    """Force safe mode, then hand off to the standard MCP server entry point."""
    os.environ["ENGRAM_SAFE_MODE"] = "1"
    # Import is deliberately deferred until after the env var is set, because
    # mcp_server decides which tools to register at import time.
    from engram.mcp_server import main as server_main

    server_main()


if __name__ == "__main__":
    main()
