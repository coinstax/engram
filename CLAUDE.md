# Claude Code Instructions

## Workflow
- Commit and check in with descriptive comments after each significant change and push to remote repo
- After completing a large task (new feature, major refactor, new version), update README.md and CHANGELOG.md before committing

## Project Memory (Engram)
This project uses Engram for persistent memory across agent sessions.
- **Start of every session**: Call `engram briefing` via MCP to understand project context
- After important decisions: `engram post_event` with type "decision" and your rationale
- To leave warnings for future agents: `engram post_event` with type "warning"
- After discovering something about the codebase: `engram post_event` with type "discovery"
- To search past context: `engram query` with search terms
- To resolve completed warnings/decisions: `engram resolve <event-id> --reason "..."`

## Testing
- Run tests with: `.venv/bin/python -m pytest tests/ -v`
- All tests must pass before committing
- Current test count: 207

## Development
- Python 3.12+, virtual env at `.venv/`
- Install: `pip install -e ".[dev]"` or `pip install -e ".[mcp]"` for MCP support
- SQLite database at `.engram/events.db`, schema currently at v4
