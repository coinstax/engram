#!/usr/bin/env python3
"""Re-run Gemini v1.1 consultation with new google-genai SDK."""

import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from google import genai

SYSTEM = (
    "You are a senior AI systems architect with expertise in large-context LLMs "
    "and developer tooling. You previously reviewed this project and advocated "
    "for semantic search and hierarchical summarization. Now review the v1.1 "
    "plan with fresh eyes. Be direct and critical."
)

PROMPT = """You previously reviewed the requirements for this project (then called "AgentBus") before v1.0 was built. Now v1.0 is complete and working. I need your critique of the v1.1 roadmap and ideas for what the next development phase should include.

Here's the current state:

---

# Engram v1.0 -- What Exists Today

Engram is a local-first project memory system for AI coding agents. It's a "project memory log with a briefing interface" -- NOT a message bus.

## Current Architecture
- Language: Python 3.12+, single dependency (click for CLI)
- Storage: SQLite with WAL mode, FTS5 full-text search
- Schema: 6 fields only (id, timestamp, event_type, agent_id, content, scope)
- Event types: discovery, decision, warning, mutation, outcome
- Content cap: 2000 characters per event
- Interfaces: CLI (click) + MCP server (FastMCP for Claude Code)
- Bootstrap: `engram init` mines git history + README/CLAUDE.md to seed events (solves cold-start)
- Briefing: Summarizes warnings, decisions, mutations, discoveries, outcomes from configurable time window
- Query: FTS5 full-text + structured filters (type, scope, since, agent_id)
- Output formats: Compact single-line (token-efficient) and JSON

## What v1.0 Does Well
- Zero-config: `engram init` and you have a useful briefing immediately
- Git bootstrap solves the cold-start problem
- FTS5 handles queries well at small scale
- Compact output is genuinely token-efficient
- MCP integration means Claude Code can use it natively

## What v1.0 Lacks (Known Gaps)
1. Agents must MANUALLY post events -- high activation energy, low compliance
2. No automatic observation of agent activity
3. No stale assumption detection
4. CLAUDE.md snippet is printed but not auto-written
5. No event priority/importance weighting
6. No hierarchical summarization (everything is flat)
7. No way to link events (no references between events)
8. No garbage collection or archival

## v1.1 Roadmap (From Original Consultation)
These were identified by GPT-4o, Gemini 2.5 Flash, and Claude Sonnet during v1.0 planning:

1. **Passive Observation** -- Auto-generate mutation events from file writes (via MCP tool wrapper or file watcher)
2. **CLAUDE.md Auto-Generation** -- `engram init` writes the agent instruction snippet directly
3. **Compact Output Improvements** -- Even more token-efficient formats
4. **Stale Assumption Detection** -- Flag decisions/assumptions invalidated by subsequent mutations

---

I need your critical review on:

1. **The v1.1 features listed above** -- Are these the right priorities? What's missing? What should be cut or deferred? Rank them by impact.

2. **The passive observation problem** -- This is the hardest and most important feature. How should it work concretely? Options include:
   - MCP tool wrapper that intercepts file writes and auto-posts mutation events
   - File system watcher (inotify/fswatch) that detects changes
   - Git diff on session end that generates events from what changed
   - Hook into Claude Code's tool use (pre/post hooks)
   - Something else entirely?

   What's the most practical approach that actually works?

3. **Event linking and references** -- Should v1.1 add the ability to link events? (e.g., an outcome event referencing the decision it evaluates) How complex should this be?

4. **Briefing intelligence** -- The current briefing is a dumb list of recent events by type. How should it get smarter? Ideas:
   - Deduplication (similar events collapsed)
   - Priority scoring (some events matter more)
   - Staleness detection (old warnings that may no longer apply)
   - Cross-referencing (decision X was contradicted by mutation Y)

5. **What's the single highest-impact thing we could build for v1.1?** Not a feature list -- the ONE thing that would most increase adoption and daily usefulness.

6. **What should we explicitly NOT build yet?** What's tempting but premature?

7. **Any new ideas?** Things nobody has suggested yet that would make this significantly more useful.

Be direct and specific. Concrete implementation suggestions over abstract principles. If you think a feature is wrong-headed, say so.
"""

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

print("Calling Gemini 2.5 Flash...")
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=PROMPT,
    config={
        "system_instruction": SYSTEM,
        "temperature": 0.7,
        "max_output_tokens": 8192,
    },
)

outdir = Path(__file__).parent.parent / "docs" / "consultations"
outdir.mkdir(parents=True, exist_ok=True)
ts = datetime.now().strftime("%Y%m%d-%H%M%S")
outpath = outdir / f"gemini-v1.1-{ts}.md"

header = f"# Engram v1.1 Consultation: GEMINI\nDate: {datetime.now().isoformat()}\nModel: gemini-2.5-flash\n\n---\n\n"
outpath.write_text(header + response.text)
print(f"Saved: {outpath}")
print(f"Length: {len(response.text)} chars")
