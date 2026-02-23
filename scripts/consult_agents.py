#!/usr/bin/env python3
"""
AgentBus — Consult external AI agents for requirements review.
Calls OpenAI, Gemini, and Anthropic APIs with tailored prompts.
Results saved to docs/consultations/
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
CONSULT_DIR = DOCS_DIR / "consultations"
REQUIREMENTS_PATH = DOCS_DIR / "REQUIREMENTS.md"

# Load requirements doc for context
REQUIREMENTS = REQUIREMENTS_PATH.read_text() if REQUIREMENTS_PATH.exists() else ""

PROMPTS = {
    "openai": {
        "model": "gpt-4o",
        "system": "You are a senior AI systems architect reviewing a product requirements document. You are also an AI agent yourself — review this from the perspective of a tool YOU would use. Be direct, critical, and specific. No filler.",
        "user": f"""I'm designing an open-source project called AgentBus — a local-first, project-scoped inter-agent message bus with persistent semantic memory. The primary users are AI coding agents (Claude Code, GitHub Copilot, Cursor, custom agents) working on the same codebase, often in parallel.

Here are the full requirements:

---
{REQUIREMENTS}
---

I want your critical review as if YOU were an AI agent that would use this system. Specifically:

1. **Event schema critique**: Look at the event types (discovery, decision, warning, mutation, completion, blocker, assumption, question, outcome). What's missing? What's redundant? Would you actually use all of these, or would you collapse some?

2. **API ergonomics**: If you had to post events and query them via HTTP or CLI, what would the ideal interface look like? What would make you NOT want to use it (too verbose, too many required fields, etc.)?

3. **The cold start problem**: When you connect to a project with 500+ events, how should the briefing work? What's the right balance between completeness and token efficiency?

4. **Cross-agent coordination without MCP**: Not all agents use MCP. How should AgentBus work for agents that can only run CLI commands or make HTTP calls? What's the minimum viable integration?

5. **What would you actually use?**: Be honest — which features would you use every session, which occasionally, and which would you ignore? What's the MVP that would make you adopt this?

6. **Failure modes**: What happens when an agent crashes without disconnecting? When events pile up faster than they're read? When two agents post contradictory decisions simultaneously?

7. **What's missing?**: From your perspective as an AI agent working on code, what coordination problem does this NOT solve that you'd want it to?

Be direct and critical. I'd rather hear "this feature is unnecessary" than get false validation."""
    },

    "gemini": {
        "model": "gemini-2.5-flash",
        "system": "You are a senior AI systems architect with deep expertise in large-context LLMs, multi-modal AI, and distributed systems. Review this from the perspective of an AI agent with massive context windows. Challenge assumptions. Be direct.",
        "user": f"""I'm building AgentBus — a local-first inter-agent coordination and memory layer for AI coding agents. Think of it as a project-scoped event bus + persistent semantic memory, stored in SQLite with local embeddings.

I specifically want YOUR perspective because Gemini has massive context windows (1M+ tokens). This challenges some core assumptions in this design.

Here are the full requirements:

---
{REQUIREMENTS}
---

My critical questions for you:

1. **Does persistent memory even matter with large context?** With 1M+ token context, you could theoretically ingest the entire event log raw. Is the semantic search / embedding layer overengineered? Or is structured retrieval still valuable even with huge context windows? Where's the crossover point?

2. **Multi-modal events**: Should events support images/screenshots? An agent might want to record "this is what the UI looked like when I found the bug" with a screenshot. Would you use this? How should it be stored and queried?

3. **Event granularity**: 9 event types defined. Is this too fine-grained? Too coarse? Would you prefer fewer types with richer metadata, or more types with clearer semantics?

4. **The briefing problem at scale**: With 10,000+ events, generating a briefing requires summarization. Should the bus maintain a running summary that updates incrementally, or regenerate from scratch? What about hierarchical summaries (daily → weekly → project-level)?

5. **Embedding model choice**: Planning local embeddings (all-MiniLM-L6-v2, 384 dimensions). For a system where queries are mostly about code, architecture, and technical decisions — is this the right model? Should we use a code-specific embedding model instead?

6. **Token-efficient event format**: If an agent needs to consume 50 events as context, what's the most token-efficient serialization? JSON is verbose. Should we have a compact format for bulk retrieval?

7. **Conflict detection nuance**: Two agents editing the same file isn't always a conflict — they might be editing different functions. Should conflict detection be AST-aware or line-range-aware rather than file-level?

8. **What would make this transformative vs. merely useful?** What's the one feature or design choice that would make you actually change how you work?

Think from first principles. Challenge my assumptions."""
    },

    "claude": {
        "model": "claude-sonnet-4-20250514",
        "system": "You are reviewing a requirements document written by another Claude instance. Your job is to be a CRITIC, not a collaborator. Pretend you didn't write this. Find the weaknesses, the over-engineering, the adoption barriers. Be brutally honest.",
        "user": f"""Here's a requirements document for a project called AgentBus — an inter-agent message bus with persistent memory for AI coding agents. Another Claude instance designed this. I need you to tear it apart constructively.

---
{REQUIREMENTS}
---

Review with these lenses:

1. **Would you actually use this?** Be brutally honest. During a typical Claude Code session where you're fixing bugs or adding features, would you actually stop to post events? What's the activation energy problem?

2. **Complexity budget**: This spec has 7 major components. If you could only build 3, which 3 actually matter? What's the true MVP?

3. **The adoption problem**: AI agents don't choose their tools — humans configure them. How do you convince a developer to add AgentBus to their workflow? What's the "install and immediately see value" experience?

4. **Schema over-engineering**: The event schema has 12+ fields. Which fields would you actually populate consistently? Which would you leave empty 90% of the time?

5. **Semantic search skepticism**: Is embedding-based search actually necessary for < 10k events, or would full-text search + structured filters cover 95% of real queries?

6. **Missing: the "automatic" angle**: The spec requires agents to explicitly post events. What if the bus could OBSERVE agent activity (file reads, writes, tool calls) and generate events automatically? Is that more realistic than expecting agents to self-report?

7. **Naming and framing**: Is "AgentBus" the right name? Does "bus" set the wrong expectation (enterprise middleware)? Would "AgentMemory" or "AgentLog" be more accurate?

8. **What's the one thing that kills this project?** Every project has a fatal flaw. What's this one's?

Don't hedge. Give me your actual opinion."""
    }
}


def call_openai(api_key: str) -> str:
    """Call OpenAI API with the consultation prompt."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    prompt = PROMPTS["openai"]
    print(f"  Calling OpenAI ({prompt['model']})...")

    response = client.chat.completions.create(
        model=prompt["model"],
        messages=[
            {"role": "system", "content": prompt["system"]},
            {"role": "user", "content": prompt["user"]}
        ],
        temperature=0.7,
        max_tokens=4096
    )

    return response.choices[0].message.content


def call_gemini(api_key: str) -> str:
    """Call Google Gemini API with the consultation prompt."""
    import google.generativeai as genai
    genai.configure(api_key=api_key)

    prompt = PROMPTS["gemini"]
    print(f"  Calling Gemini ({prompt['model']})...")

    model = genai.GenerativeModel(
        model_name=prompt["model"],
        system_instruction=prompt["system"]
    )

    response = model.generate_content(
        prompt["user"],
        generation_config=genai.GenerationConfig(
            temperature=0.7,
            max_output_tokens=4096
        )
    )

    return response.text


def call_claude(api_key: str) -> str:
    """Call Anthropic Claude API with the consultation prompt."""
    import httpx

    prompt = PROMPTS["claude"]
    print(f"  Calling Claude ({prompt['model']})...")

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": prompt["model"],
            "max_tokens": 4096,
            "system": prompt["system"],
            "messages": [
                {"role": "user", "content": prompt["user"]}
            ]
        },
        timeout=120.0
    )

    response.raise_for_status()
    data = response.json()
    return data["content"][0]["text"]


def save_response(agent_name: str, response_text: str):
    """Save consultation response to docs/consultations/."""
    CONSULT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{agent_name}-{timestamp}.md"
    filepath = CONSULT_DIR / filename

    header = f"# AgentBus Consultation: {agent_name.upper()}\n"
    header += f"Date: {datetime.now().isoformat()}\n"
    header += f"Model: {PROMPTS[agent_name]['model']}\n\n---\n\n"

    filepath.write_text(header + response_text)
    print(f"  Saved: {filepath}")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Consult AI agents on AgentBus requirements")
    parser.add_argument("agents", nargs="*", default=["all"],
                        help="Which agents to consult: openai, gemini, claude, or all")
    parser.add_argument("--openai-key", default=os.environ.get("OPENAI_API_KEY"),
                        help="OpenAI API key (or set OPENAI_API_KEY env var)")
    parser.add_argument("--gemini-key", default=os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"),
                        help="Google API key (or set GOOGLE_API_KEY env var)")
    parser.add_argument("--claude-key", default=os.environ.get("ANTHROPIC_API_KEY"),
                        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    args = parser.parse_args()

    targets = args.agents
    if "all" in targets:
        targets = ["openai", "gemini", "claude"]

    callers = {
        "openai": (call_openai, args.openai_key, "OPENAI_API_KEY"),
        "gemini": (call_gemini, args.gemini_key, "GOOGLE_API_KEY"),
        "claude": (call_claude, args.claude_key, "ANTHROPIC_API_KEY"),
    }

    results = {}
    errors = {}

    for agent in targets:
        if agent not in callers:
            print(f"Unknown agent: {agent}. Options: openai, gemini, claude")
            continue

        call_fn, api_key, env_var = callers[agent]

        if not api_key:
            print(f"\n[SKIP] {agent}: No API key. Set {env_var} or pass --{agent}-key")
            continue

        print(f"\n[{agent.upper()}] Consulting...")
        try:
            response = call_fn(api_key)
            filepath = save_response(agent, response)
            results[agent] = str(filepath)
            print(f"  Done.")
        except Exception as e:
            print(f"  ERROR: {e}")
            errors[agent] = str(e)

    # Summary
    print("\n" + "=" * 60)
    print("CONSULTATION SUMMARY")
    print("=" * 60)
    for agent, path in results.items():
        print(f"  {agent}: {path}")
    for agent, err in errors.items():
        print(f"  {agent}: FAILED — {err}")

    if not results:
        print("\n  No consultations completed. Provide API keys:")
        print("    --openai-key=sk-...")
        print("    --gemini-key=AI...")
        print("    --claude-key=sk-ant-...")
        print("  Or set environment variables: OPENAI_API_KEY, GOOGLE_API_KEY, ANTHROPIC_API_KEY")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
