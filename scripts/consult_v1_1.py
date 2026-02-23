#!/usr/bin/env python3
"""
Engram v1.1 — Consult external AI agents for next development phase.
Calls OpenAI and Gemini APIs with the current v1.0 state + v1.1 roadmap.
Results saved to docs/consultations/
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
CONSULT_DIR = PROJECT_ROOT / "docs" / "consultations"

# Load .env
load_dotenv(PROJECT_ROOT / ".env")

CONTEXT = """
# Engram v1.0 — What Exists Today

Engram is a local-first project memory system for AI coding agents. It's a "project memory log with a briefing interface" — NOT a message bus.

## Current Architecture
- **Language**: Python 3.12+, single dependency (click for CLI)
- **Storage**: SQLite with WAL mode, FTS5 full-text search
- **Schema**: 6 fields only (id, timestamp, event_type, agent_id, content, scope)
- **Event types**: discovery, decision, warning, mutation, outcome
- **Content cap**: 2000 characters per event
- **Interfaces**: CLI (click) + MCP server (FastMCP for Claude Code)
- **Bootstrap**: `engram init` mines git history + README/CLAUDE.md to seed events (solves cold-start)
- **Briefing**: Summarizes warnings, decisions, mutations, discoveries, outcomes from configurable time window
- **Query**: FTS5 full-text + structured filters (type, scope, since, agent_id)
- **Output formats**: Compact single-line (token-efficient) and JSON

## What v1.0 Does Well
- Zero-config: `engram init` and you have a useful briefing immediately
- Git bootstrap solves the cold-start problem
- FTS5 handles queries well at small scale
- Compact output is genuinely token-efficient
- MCP integration means Claude Code can use it natively

## What v1.0 Lacks (Known Gaps)
1. Agents must MANUALLY post events — high activation energy, low compliance
2. No automatic observation of agent activity
3. No stale assumption detection
4. CLAUDE.md snippet is printed but not auto-written
5. No event priority/importance weighting
6. No hierarchical summarization (everything is flat)
7. No way to link events (no references between events)
8. No garbage collection or archival

## v1.1 Roadmap (From Original Consultation)
These were identified by GPT-4o, Gemini 2.5 Flash, and Claude Sonnet during v1.0 planning:

1. **Passive Observation** — Auto-generate mutation events from file writes (via MCP tool wrapper or file watcher)
2. **CLAUDE.md Auto-Generation** — `engram init` writes the agent instruction snippet directly
3. **Compact Output Improvements** — Even more token-efficient formats
4. **Stale Assumption Detection** — Flag decisions/assumptions invalidated by subsequent mutations
"""

PROMPT_TEMPLATE = """You previously reviewed the requirements for this project (then called "AgentBus") before v1.0 was built. Now v1.0 is complete and working. I need your critique of the v1.1 roadmap and ideas for what the next development phase should include.

Here's the current state:

---
{context}
---

I need your critical review on:

1. **The v1.1 features listed above** — Are these the right priorities? What's missing? What should be cut or deferred? Rank them by impact.

2. **The passive observation problem** — This is the hardest and most important feature. How should it work concretely? Options include:
   - MCP tool wrapper that intercepts file writes and auto-posts mutation events
   - File system watcher (inotify/fswatch) that detects changes
   - Git diff on session end that generates events from what changed
   - Hook into Claude Code's tool use (pre/post hooks)
   - Something else entirely?

   What's the most practical approach that actually works?

3. **Event linking and references** — Should v1.1 add the ability to link events? (e.g., an outcome event referencing the decision it evaluates) How complex should this be?

4. **Briefing intelligence** — The current briefing is a dumb list of recent events by type. How should it get smarter? Ideas:
   - Deduplication (similar events collapsed)
   - Priority scoring (some events matter more)
   - Staleness detection (old warnings that may no longer apply)
   - Cross-referencing (decision X was contradicted by mutation Y)

5. **What's the single highest-impact thing we could build for v1.1?** Not a feature list — the ONE thing that would most increase adoption and daily usefulness.

6. **What should we explicitly NOT build yet?** What's tempting but premature?

7. **Any new ideas?** Things nobody has suggested yet that would make this significantly more useful.

Be direct and specific. Concrete implementation suggestions over abstract principles. If you think a feature is wrong-headed, say so.
"""

PROMPTS = {
    "openai": {
        "model": "gpt-4o",
        "system": "You are a senior AI systems architect. You are also an AI coding agent yourself — you use tools like this daily. Review from the perspective of a tool YOU would want to use. Be direct, critical, and specific.",
        "user": PROMPT_TEMPLATE.format(context=CONTEXT),
    },
    "gemini": {
        "model": "gemini-2.5-flash",
        "system": "You are a senior AI systems architect with expertise in large-context LLMs and developer tooling. You previously reviewed this project and advocated for semantic search and hierarchical summarization. Now review the v1.1 plan with fresh eyes. Be direct and critical.",
        "user": PROMPT_TEMPLATE.format(context=CONTEXT),
    },
}


def call_openai(api_key: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    prompt = PROMPTS["openai"]
    print(f"  Calling OpenAI ({prompt['model']})...")
    response = client.chat.completions.create(
        model=prompt["model"],
        messages=[
            {"role": "system", "content": prompt["system"]},
            {"role": "user", "content": prompt["user"]},
        ],
        temperature=0.7,
        max_tokens=4096,
    )
    return response.choices[0].message.content


def call_gemini(api_key: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    prompt = PROMPTS["gemini"]
    print(f"  Calling Gemini ({prompt['model']})...")
    model = genai.GenerativeModel(
        model_name=prompt["model"],
        system_instruction=prompt["system"],
    )
    response = model.generate_content(
        prompt["user"],
        generation_config=genai.GenerationConfig(
            temperature=0.7,
            max_output_tokens=4096,
        ),
    )
    return response.text


def save_response(agent_name: str, response_text: str) -> Path:
    CONSULT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{agent_name}-v1.1-{timestamp}.md"
    filepath = CONSULT_DIR / filename
    header = f"# Engram v1.1 Consultation: {agent_name.upper()}\n"
    header += f"Date: {datetime.now().isoformat()}\n"
    header += f"Model: {PROMPTS[agent_name]['model']}\n\n---\n\n"
    filepath.write_text(header + response_text)
    print(f"  Saved: {filepath}")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Consult AI agents on Engram v1.1")
    parser.add_argument("agents", nargs="*", default=["all"],
                        help="Which agents: openai, gemini, or all")
    args = parser.parse_args()

    targets = args.agents
    if "all" in targets:
        targets = ["openai", "gemini"]

    callers = {
        "openai": (call_openai, os.environ.get("OPENAI_API_KEY")),
        "gemini": (call_gemini, os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")),
    }

    results = {}
    for agent in targets:
        if agent not in callers:
            print(f"Unknown agent: {agent}")
            continue
        call_fn, api_key = callers[agent]
        if not api_key:
            print(f"\n[SKIP] {agent}: No API key set")
            continue
        print(f"\n[{agent.upper()}] Consulting...")
        try:
            response = call_fn(api_key)
            save_response(agent, response)
            results[agent] = response
        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\n{'='*60}")
    print(f"Completed: {', '.join(results.keys()) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
