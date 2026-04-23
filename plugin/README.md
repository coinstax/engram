# Engram — Claude Code plugin

This directory packages Engram as a Claude Code plugin bundle. One install wires up the MCP server, the passive-observation hooks, and a set of slash-command skills.

**Status:** work in progress, shipping with Engram v1.7.0.

## Contents

| Path | Purpose |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest (name, version, keywords) |
| `.mcp.json` | Registers the `engram-mcp` server; injects `ENGRAM_PROJECT_DIR=${PWD}` |
| `hooks/hooks.json` | PostToolUse (Write/Edit/Bash) + SessionStart, same commands as CLI-installed hooks |
| `skills/<name>/SKILL.md` | User- and model-invokable slash commands (e.g., `/engram:briefing`) |

## Prerequisites

The plugin assumes `engram` and `engram-mcp` are on PATH. Install the Python package:

```bash
pip install engram[mcp]
```

(Once Engram is on PyPI; until then, `pip install -e ".[mcp]"` from a repo checkout.)

## Development install

Load the plugin without copying:

```bash
claude --plugin-dir /path/to/engram/plugin
```

Edit a plugin file and run `/reload-plugins` in the session to pick up changes without restarting.

## Migrating from CLI-installed hooks

If a project already ran `engram hooks install`, run:

```bash
engram hooks uninstall
```

before enabling the plugin, to avoid duplicate event capture. (The v1.7.0 release notes will document whether Claude Code dedupes hook entries automatically; until then, treat manual uninstall as required.)

## First run

On first launch in a project that has no `.engram/` directory, the plugin's SessionStart hook initializes Engram automatically: creates `.engram/events.db`, seeds events from the last 100 git commits, and registers a session. The first briefing announces this with a one-line banner.

The plugin does **not** modify your `CLAUDE.md`. Agent-facing guidance is delivered through the MCP server's `instructions` field and the plugin's SKILL.md files. If you want the `CLAUDE.md` snippet (for non-plugin or headless use), run `engram init` manually **before** the first plugin launch — once `.engram/` exists, subsequent `engram init` runs short-circuit with "already initialized" and do not modify CLAUDE.md.

## Current state

Skills shipping today:

- `/engram:briefing` — the project briefing

Landing next in the v1.7.0 branch:

- `/engram:post-decision`
- `/engram:query`
- `/engram:checkpoint-save`
- `/engram:checkpoint-restore`

See [../docs/ROADMAP.md](../docs/ROADMAP.md) for the full v1.7 scope and the open design items still under test.
