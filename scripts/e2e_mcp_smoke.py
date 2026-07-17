"""End-to-end smoke test for the Engram MCP server, driven over stdio.

This exercises the same path Claude Code uses to load the plugin: it launches
the `engram-mcp` console script in a project directory and talks to it with a
real MCP client, then checks the server operates on the *correct* database.

It exists mainly to guard the Windows failure mode from issue #1, where the
server silently read an empty DB in a junk directory. Pure-Python unit tests
cannot catch that class of bug — only launching the process the way the harness
does can. Runs on every OS in CI; the Windows leg is the one that matters.

Exit code 0 = pass, non-zero = fail. Prints a short trace of each check.
"""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _require(cond, msg):
    if not cond:
        print(f"FAIL: {msg}")
        raise SystemExit(1)
    print(f"ok: {msg}")


def _tool_text(result):
    """Concatenate the text content of an MCP tool result."""
    parts = []
    for block in result.content:
        parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


def _run(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"FAIL: command {cmd} exited {proc.returncode}")
        print(proc.stdout)
        print(proc.stderr)
        raise SystemExit(1)
    return proc.stdout


async def _drive(project: Path, engram_mcp: str):
    # Launch the server in the project dir with NO env override — the exact
    # scenario the fixed plugin relies on (server resolves cwd itself).
    params = StdioServerParameters(command=engram_mcp, args=[], cwd=str(project))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = {t.name for t in (await session.list_tools()).tools}
            _require("briefing" in tools and "status" in tools,
                     f"server advertised memory tools ({len(tools)} total)")
            _require("start_consultation" in tools,
                     "consult tools present in normal mode")

            status = json.loads(_tool_text(await session.call_tool("status", {})))
            _require(status["project_name"] == "e2e-smoke",
                     f"status resolved the real project: {status['project_name']!r}")
            _require(status["total_events"] == 2,
                     f"status read the populated DB (total_events={status['total_events']})")
            _require(status.get("external_llm_tools") is True,
                     "status reports external_llm_tools=true in normal mode")

            brief = _tool_text(await session.call_tool("briefing", {}))
            _require("e2e-smoke" in brief, "briefing rendered the real project")

            # Round-trip a write through MCP, read it back through MCP.
            # Single-token marker: FTS5 treats hyphens as separators.
            await session.call_tool("post_event", {
                "event_type": "discovery", "content": "mcproundtripmarker via mcp",
            })
            q = _tool_text(await session.call_tool("query", {"text": "mcproundtripmarker"}))
            _require("mcproundtripmarker" in q, "MCP write is visible to MCP query")


async def _drive_bad_env(project: Path, engram_mcp: str):
    # Simulate the Windows bug: an unexpanded ${PWD} literal reaches the server.
    # The loud guard must turn this into an error, not a silent empty DB.
    # Merge with the inherited environment: StdioServerParameters.env replaces
    # the whole environment, and on Windows stripping PATH/SYSTEMROOT stops the
    # server from even launching. We only want to inject the one bad value.
    params = StdioServerParameters(
        command=engram_mcp, args=[], cwd=str(project),
        env={**os.environ, "ENGRAM_PROJECT_DIR": "${PWD}"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("status", {})
            _require(result.isError, "unexpanded ${PWD} project dir errors loudly")
            _require("unexpanded" in _tool_text(result).lower(),
                     "error message explains the unexpanded variable")


def main():
    engram = shutil.which("engram")
    engram_mcp = shutil.which("engram-mcp")
    _require(engram is not None, "engram console script is on PATH")
    _require(engram_mcp is not None, "engram-mcp console script is on PATH")

    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "e2e-smoke"
        project.mkdir()

        # Init (no git in the temp dir -> 0 seeded), then post two events via CLI.
        _run([engram, "-p", str(project), "init", "--no-claude-md"])
        _run([engram, "-p", str(project), "post", "-t", "decision",
              "-c", "chose sqlite for storage"])
        _run([engram, "-p", str(project), "post", "-t", "warning",
              "-c", "do not commit events.db"])

        asyncio.run(_drive(project, engram_mcp))
        asyncio.run(_drive_bad_env(project, engram_mcp))

        # The Windows bug created a literal "${PWD}" directory. Assert none of
        # the working dirs we used grew one.
        for base in (project, Path(tmp), Path.cwd()):
            junk = base / "${PWD}"
            _require(not junk.exists(), f"no junk '${{PWD}}' dir under {base}")

    print("\nE2E MCP smoke passed.")


if __name__ == "__main__":
    main()
