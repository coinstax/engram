# AgentBus — Consultation Prompts for External AI Agents

## Prompt for OpenAI (GPT-4o / o3)

### Focus: Agent-agnostic design, API ergonomics, non-MCP perspective

```
I'm designing an open-source project called AgentBus — a local-first, project-scoped inter-agent message bus with persistent semantic memory. The primary users are AI coding agents (Claude Code, GitHub Copilot, Cursor, custom agents) working on the same codebase, often in parallel.

Core features:
1. Append-only event store (SQLite) with typed events: discovery, decision, warning, mutation, completion, blocker, assumption, question, outcome
2. Semantic query interface — natural language + structured queries over events, using local embeddings
3. Subscription/watch system — agents subscribe to file scope patterns or event types, get notified of relevant changes
4. Conflict detection — detects when two agents modify overlapping files or make contradictory decisions
5. Project briefing — single-call "catch me up" summary for new agent sessions
6. Outcome tracking — links actions to results, building project-specific lessons learned
7. Interfaces: CLI, local HTTP API, MCP server

Storage: SQLite + local vector DB. No cloud, no servers, zero-config.

I want your critical review as if YOU were an AI agent that would use this system. Specifically:

1. **Event schema critique**: Look at the event types (discovery, decision, warning, mutation, completion, blocker, assumption, question, outcome). What's missing? What's redundant? Would you actually use all of these, or would you collapse some?

2. **API ergonomics**: If you had to post events and query them via HTTP or CLI, what would the ideal interface look like? What would make you NOT want to use it (too verbose, too many required fields, etc.)?

3. **The cold start problem**: When you connect to a project with 500+ events, how should the briefing work? What's the right balance between completeness and token efficiency?

4. **Cross-agent coordination without MCP**: Not all agents use MCP. How should AgentBus work for agents that can only run CLI commands or make HTTP calls? What's the minimum viable integration?

5. **What would you actually use?**: Be honest — which features would you use every session, which occasionally, and which would you ignore? What's the MVP that would make you adopt this?

6. **Failure modes**: What happens when an agent crashes without disconnecting? When events pile up faster than they're read? When two agents post contradictory decisions simultaneously?

7. **What's missing?**: From your perspective as an AI agent working on code, what coordination problem does this NOT solve that you'd want it to?

Be direct and critical. I'd rather hear "this feature is unnecessary" than get false validation.
```

## Prompt for Google Gemini

### Focus: Large context implications, multi-modal events, scaling assumptions

```
I'm building AgentBus — a local-first inter-agent coordination and memory layer for AI coding agents. Think of it as a project-scoped event bus + persistent semantic memory, stored in SQLite with local embeddings.

I specifically want YOUR perspective because Gemini has massive context windows (1M+ tokens). This challenges some of my core assumptions.

Here's the architecture:
- Append-only event store with typed events (discovery, decision, warning, mutation, blocker, outcome, etc.)
- Local embedding-based semantic search for querying events
- Subscription system for real-time coordination
- Project briefing endpoint that summarizes project state for new sessions
- Conflict detection when agents overlap on files
- Outcome tracking to build lessons learned

My critical questions for you:

1. **Does persistent memory even matter with large context?** With 1M+ token context, you could theoretically ingest the entire event log raw. Is the semantic search / embedding layer overengineered? Or is structured retrieval still valuable even with huge context windows? Where's the crossover point?

2. **Multi-modal events**: Should events support images/screenshots? An agent might want to record "this is what the UI looked like when I found the bug" with a screenshot. Would you use this? How should it be stored and queried?

3. **Event granularity**: I defined 9 event types. Is this too fine-grained? Too coarse? Would you prefer fewer types with richer metadata, or more types with clearer semantics?

4. **The briefing problem at scale**: With 10,000+ events, generating a briefing requires summarization. Should the bus maintain a running summary that updates incrementally, or regenerate from scratch? What about hierarchical summaries (daily → weekly → project-level)?

5. **Embedding model choice**: I'm planning local embeddings (all-MiniLM-L6-v2, 384 dimensions). For a system where queries are mostly about code, architecture, and technical decisions — is this the right model? Should we use a code-specific embedding model instead?

6. **Token-efficient event format**: If an agent needs to consume 50 events as context, what's the most token-efficient serialization? JSON is verbose. Should we have a compact format for bulk retrieval?

7. **Conflict detection nuance**: Two agents editing the same file isn't always a conflict — they might be editing different functions. Should conflict detection be AST-aware or line-range-aware rather than file-level?

8. **What would make this transformative vs. merely useful?** What's the one feature or design choice that would make you actually change how you work?

Think from first principles. Challenge my assumptions.
```

## Prompt for Perplexity (Research-Focused)

### Focus: Prior art deep dive, academic research, existing implementations

```
Research the following for an open-source project called AgentBus — a local-first inter-agent message bus with persistent memory for AI coding agents:

1. **Existing implementations**: Are there any open-source projects that specifically solve inter-agent coordination for AI coding agents (not general agent frameworks)? Specifically looking for:
   - Agent-to-agent communication in developer tooling
   - Persistent memory layers designed for code-editing AI agents
   - Event bus architectures used in multi-agent AI systems

2. **Academic research**: Find recent papers (2024-2026) on:
   - Multi-agent coordination protocols for software engineering tasks
   - Persistent memory architectures for LLM-based agents
   - Conflict resolution in collaborative AI code editing
   - Event sourcing patterns applied to AI agent systems

3. **SQLite for event stores**: What are the real-world performance limits of SQLite as an event store? Specifically:
   - Concurrent write performance with WAL mode
   - Performance with 100k+ rows and full-text search
   - SQLite-vss or similar extensions for vector search — production readiness?

4. **Local embedding models for code**: What are the best lightweight embedding models (< 500MB) for technical/code content as of early 2026? Compare:
   - all-MiniLM-L6-v2
   - CodeBERT variants
   - Nomic Embed
   - Any code-specific models

5. **MCP server implementation patterns**: What are the best practices for building an MCP server in Python? Any reference implementations for stateful MCP servers (not just tool wrappers)?

Provide specific URLs, GitHub repos, and paper citations.
```

## Prompt for Claude (Separate Session — Self-Review)

### Focus: Honest self-critique as both designer and user

```
I'm going to share a requirements document for a project I (another Claude instance) designed called AgentBus. I need you to review it as a CRITIC, not a collaborator. Pretend you didn't write this.

[PASTE FULL REQUIREMENTS.md HERE]

Review this with these specific lenses:

1. **Would you actually use this?** Be brutally honest. During a typical Claude Code session where you're fixing bugs or adding features, would you actually stop to post events? What's the activation energy problem?

2. **Complexity budget**: This spec has 7 major components. If you could only build 3, which 3 actually matter? What's the true MVP?

3. **The adoption problem**: AI agents don't choose their tools — humans configure them. How do you convince a developer to add AgentBus to their workflow? What's the "install and immediately see value" experience?

4. **Schema over-engineering**: The event schema has 12+ fields. Which fields would you actually populate consistently? Which would you leave empty 90% of the time?

5. **Semantic search skepticism**: Is embedding-based search actually necessary for < 10k events, or would full-text search + structured filters cover 95% of real queries?

6. **Missing: the "automatic" angle**: The spec requires agents to explicitly post events. What if the bus could OBSERVE agent activity (file reads, writes, tool calls) and generate events automatically? Is that more realistic than expecting agents to self-report?

7. **Naming and framing**: Is "AgentBus" the right name? Does "bus" set the wrong expectation (enterprise middleware)? Would "AgentMemory" or "AgentLog" be more accurate?

8. **What's the one thing that kills this project?** Every project has a fatal flaw. What's this one's?

Don't hedge. Give me your actual opinion.
```

## Prompt for a Systems Architect (Human or AI)

### Focus: Infrastructure reality check

```
I'm building a developer tool called AgentBus — a local SQLite-based event store + semantic search layer that AI coding agents use to coordinate and share knowledge.

Architecture:
- SQLite with WAL mode for concurrent access
- Local embeddings (all-MiniLM-L6-v2) stored alongside events
- File-based notification system (JSONL files per subscriber)
- Optional lightweight HTTP server for real-time features
- MCP server for Claude Code integration

I need a reality check on:

1. **SQLite concurrency**: Multiple agents writing events simultaneously. WAL mode handles concurrent reads well, but what about write contention with 3-5 agents posting events within the same second? Do I need write queuing?

2. **File-based notifications**: Each agent gets a JSONL file that events are appended to. Is this robust? What about file locking on Linux/Mac? Race conditions with concurrent appends?

3. **Embedding generation on write**: Every event post triggers embedding generation (~50ms with a local model). Is this acceptable latency? Should embeddings be generated async?

4. **Process lifecycle**: Agents crash. The "session" concept requires heartbeats + stale detection. What's the simplest reliable way to detect a dead agent process on a local machine?

5. **Data growth**: 10k events with embeddings (384-dim float32). What's the realistic storage footprint? When does SQLite FTS5 + vector search start to degrade?

6. **The HTTP server question**: Should the HTTP server be a separate process, or embedded in each agent's process? A shared server is simpler but adds a dependency. Per-agent embedded servers mean no central coordination.

7. **Cross-platform gotchas**: This needs to work on Linux and macOS. Any SQLite or file-locking differences I should worry about?

Give me the engineering reality, not the ideal architecture.
```
