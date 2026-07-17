"""Guards for the shipped Claude Code plugin configuration."""

import json
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugin"


def test_mcp_json_has_no_unexpanded_shell_vars():
    """.mcp.json must not inject a shell-variable literal like ${PWD}.

    cmd.exe / PowerShell never set PWD, so ${PWD} reached engram-mcp verbatim
    on Windows and every MCP tool operated on the wrong (empty) database.
    engram-mcp defaults to its working directory, so no env override is needed.
    """
    raw = (PLUGIN_DIR / ".mcp.json").read_text()
    assert "${" not in raw, f"unexpanded shell variable in .mcp.json: {raw!r}"

    cfg = json.loads(raw)
    server = cfg["mcpServers"]["engram"]
    # No ENGRAM_PROJECT_DIR default — the server resolves cwd itself.
    assert "ENGRAM_PROJECT_DIR" not in server.get("env", {})
