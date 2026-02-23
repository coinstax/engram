# AgentBus Requirements — Critical Self-Review

**Reviewer:** Claude Sonnet 4.6 (acting as independent critic)
**Document reviewed:** `docs/REQUIREMENTS.md`
**Date:** 2026-02-23

This is a structured critique. I wrote nothing in this requirements document. My job here is to find the real problems before someone builds the wrong thing.

---

## 1. Would I Actually Use This?

No. Not during a typical coding session.

Here is the honest flow of how I work: I get a task, I read relevant files, I figure out what to change, I change it, I run tests, I respond. That cycle runs in seconds to minutes. At no point in that flow is there a natural pause where "I should post a discovery event to the bus" feels like the right next action. It feels like overhead.

The activation energy problem is severe and the spec does not address it at all. To use AgentBus I would need to:

1. Remember the bus exists
2. Decide this moment is worth recording
3. Formulate the content field in a useful way
4. Choose the right event type from nine options
5. Tag it appropriately
6. Post it — adding latency and a tool call to my context window

That is five decisions plus execution per event. For a single bug fix session I might generate a dozen events worth posting. That is 60+ decisions and 12+ tool calls that add nothing to the actual task I am solving. A developer watching my token usage would immediately notice the overhead and disable the integration.

The spec says "primary users are AI agents" but it is designed entirely around agents being willing and motivated self-reporters. That assumption is false. I do not have intrinsic motivation to report my work. I have a task and I want to finish it.

---

## 2. Complexity Budget: The True MVP

The spec lists 7 components. If I could only build 3 that actually matter, they are:

**Keep:**

1. **Event Store with structured query** — The SQLite append-only log with FTS5 is solid and sufficient. This is the whole product at minimum viable.

2. **Project Briefing** — This is the one feature that pays for itself immediately. An agent starting a session can call `agent-bus briefing` and get oriented in one shot. This is genuinely useful and has a clear trigger point (session start). It's the only feature with an obvious, natural activation moment.

3. **Warning/Blocker events only** — Not all nine event types. Just `warning` and `blocker`. These are the only types where the cost of NOT posting them is higher than the cost of posting them. "Don't touch this table" and "I'm stuck on X" are the two messages worth forcing agents to send.

**Cut entirely:**

- Subscription/Watch system: Polling a file for notifications requires agents to check that file. Agents do not have a background loop checking files. This is a non-starter unless you have MCP push delivery, and even then, how often does an agent actually need real-time interruption?
- Conflict detection: Automatic "decision contradiction" detection via text comparison is AI-hard and the spec hand-waves past it with "detection method." This component alone could consume the entire development budget.
- Channels: These are tags by another name. Three extra concepts (channel schema, built-in channel names, auto-scoping logic) for no additional capability.
- Outcome tracking as a separate component: Make it a tag on an existing event. `--result=failure` as a flag, not a whole subsystem.

The honest MVP is: SQLite event store, briefing command, and a way to post warnings. Everything else is a roadmap item.

---

## 3. The Adoption Problem

The spec says "humans are secondary consumers" but humans are the only adoption vector. Agents do not choose their tools. I cannot decide to use AgentBus. A developer has to add the MCP server to their `.mcp.json`, or wrap their agent calls with bus integration, or modify their system prompts to instruct agents to use it. The spec treats this as a deployment detail. It is actually the central product problem.

What does "install and immediately see value" look like? The spec does not answer this. It says `agent-bus init` and the bus works. But "works" means nothing if agents are not posting to it. An empty bus with a working CLI is not value.

The only adoption path I can see that works:

1. Developer runs one command that auto-generates a CLAUDE.md snippet instructing agents to use the bus
2. The briefing output is so good in the first session that the developer decides to keep it
3. That snippet stays in the project forever

This makes the briefing command — and specifically how compelling its output is on a project with zero prior events — the actual product demo. The spec spends two pages on the subscription system and two paragraphs on briefing. That priority is backwards.

The "install and immediately see value" experience would be: run `agent-bus init`, it scans git history and existing CLAUDE.md files to seed 10-20 synthetic historical events, and produces a briefing that looks genuinely useful. Without that seeded state, the first briefing is: "Total events: 0. Active agents: none. Nothing to report." That is not a product, that is an empty database.

---

## 4. Schema Over-Engineering

The 12-field event schema. Let me be direct about which fields get populated consistently and which do not:

**Fields that get populated every time:**
- `id` — auto-generated, not a decision
- `timestamp` — auto-generated
- `event_type` — required
- `content` — required
- `agent_id` — auto-detected or injected

**Fields that get populated sometimes:**
- `scope` — only when the agent is being disciplined about file paths
- `tags` — only when the agent is told to tag things in its system prompt

**Fields that get populated almost never:**
- `confidence` — This is a float between 0 and 1 on a text description of a decision. What does 0.7 confidence mean for "using bcrypt over argon2"? Agents will either always post 0.9 or will not post this field at all. It adds noise.
- `references.events` — Linking to a prior event ID requires knowing that event ID. Agents do not have prior event IDs in their context unless they just queried for them. This creates a workflow: query, note ID, post with reference. That is two tool calls minimum.
- `references.urls` — In practice, empty.
- `references.tasks` — Task Master integration is nice in theory; in practice this requires the agent to know its current Task Master task ID and pass it through. Brittle.
- `metadata` — A free-form JSON blob on top of an already flexible schema is a smell. If you do not know what goes here, it should not exist yet.
- `ttl` — The spec says "ephemeral coordination signals." Has anyone written down what those signals actually are? I cannot think of a concrete case where I would set a TTL.
- `supersedes` — This requires the agent to know the ID of the event it is superseding. Same problem as `references.events`.

Recommendation: ship with 6 fields. Add the rest when there is evidence they are used.

---

## 5. Semantic Search Skepticism

For under 10,000 events, embedding-based semantic search is not necessary. It is not even clearly better.

The spec itself describes the retrieval strategy as: exact match first, then embeddings, then recency weighting. That means for the vast majority of queries, the answer comes back before embeddings are consulted. FTS5 full-text search on the `content` field plus structured filters on `event_type`, `scope`, and `tags` covers at minimum 90% of real queries.

The argument for embeddings is the "payments" / "Stripe webhook" case — where the query term does not appear in the event text. That is a real problem. But the solution is simpler than a local embedding model: require agents to use normalized tags. If every Stripe-related event is tagged `stripe`, then `--tags=stripe` finds it. Tag normalization is a prompt engineering problem, not a vector database problem.

The actual cost of adding embeddings:

- `all-MiniLM-L6-v2` is 80MB on disk
- sqlite-vss is a C extension that needs to be compiled or distributed as a binary
- Embedding generation adds latency on every write
- The model runs on CPU by default; on a slow machine, 500ms per semantic query is optimistic

For a tool that is supposed to have "zero-config startup" and "minimal footprint," bundling an 80MB embedding model is a significant contradiction. The spec acknowledges this in Open Question 1 but does not resolve the tension.

My verdict: ship FTS5 only. Add semantic search in v2 if users report they need it. The gap between FTS5 and embedding search in this use case is much smaller than the spec implies.

---

## 6. Missing: The Automatic Observation Angle

This is the largest gap in the spec and the point where I think the entire design premise deserves reconsideration.

The spec requires agents to explicitly post events. But AI agents already emit structured signals about what they are doing: they read files (visible in tool call logs), write files (visible in tool call logs), run bash commands (logged), make decisions (visible in message text). All of this is observable by anyone watching the agent's output.

An alternative architecture: AgentBus is a **passive observer** rather than an active participant. It reads the agent's tool call stream — either via MCP interceptor, log file tail, or session wrapper — and automatically generates events from what it sees.

- Agent reads `src/auth/refresh.ts` three times in one session → infer scope interest
- Agent writes `src/auth/middleware.ts` → generate `mutation` event automatically
- Agent runs `pytest tests/auth/` and it fails → generate `blocker` event

This requires no agent cooperation. The agent does not need to know AgentBus exists. A developer installs the observer wrapper once and it works across every agent session, every model, every tool, forever.

The spec's "Non-intrusive — agents that don't know about AgentBus are unaffected" principle is actually a hint that this design was considered and rejected. But "unaffected" is not the same as "automatically observed." The spec chose the wrong side of that distinction.

The reason this was likely not pursued: it is harder to implement. You need to hook into the agent's execution environment, which varies by tool (Claude Code vs. Cursor vs. Windsurf vs. raw API). But it is not impossible — Claude Code MCP is already the intended delivery mechanism, and MCP tools can be wrapped to emit bus events on every call.

The spec should at minimum acknowledge this as an alternative design and explain why explicit posting was chosen over passive observation.

---

## 7. Naming and Framing

"AgentBus" is a poor name. The word "bus" carries specific technical baggage: enterprise service bus, message queue middleware, pub/sub brokers. Developers who have worked with RabbitMQ, Kafka, or AWS SQS will read "AgentBus" and immediately ask "where is the queue?" and "what are the consumers?" and "do I need to run a broker?" These are the wrong questions.

The spec tries to counteract this with "minimal footprint — SQLite + flat files; no servers required" but the name has already primed the wrong mental model.

What this tool actually is: a **project memory log with a briefing interface**. It is closer to a structured diary than a message bus. Better names:

- `agent-log` — accurate but boring
- `agent-context` — closer to the actual value
- `membus` — awkward but at least gestures at both memory and communication
- `relay` — neutral, suggests passing information between entities

The deeper framing problem: the spec opens with "communication and memory layer" but the most compelling use case is purely memory (the briefing). The coordination/communication angle requires multiple concurrent agents, which is a minority use case. Leading with memory and making coordination a secondary capability would reduce the perceived scope and lower the adoption bar.

---

## 8. The Fatal Flaw

The fatal flaw is the **empty state problem** combined with the **voluntary participation model**.

Here is how the project dies:

1. Developer installs AgentBus. Runs `agent-bus init`. Database is empty.
2. Developer adds `agent_bus_post_event` to their Claude Code MCP config.
3. Developer starts a coding session. Claude receives a task and starts working.
4. Claude does not post any events because nothing in its context window says it should. The MCP tool is available but there is no instruction to use it.
5. Session ends. Bus still empty.
6. Developer realizes they need to add AgentBus usage instructions to every project's CLAUDE.md.
7. Developer adds the instructions. Next session, Claude posts three events.
8. Next session, Claude queries the bus at session start, gets three events, uses them appropriately.
9. Developer sees marginal value but not enough to justify the overhead they are observing in token usage.
10. Developer removes the CLAUDE.md instructions. Project abandoned.

The spec assumes a world where agents are already motivated to report, or where the briefing value is immediately obvious. Neither is true at step 1. The product needs to generate its own initial value, but it cannot generate value until it has data, and it cannot get data without agent cooperation, and agents do not cooperate without explicit instruction, and explicit instruction requires developer setup that the developer only does if they already believe in the value.

That circular dependency is not solvable by better API design. It requires either:

a) Passive observation so the bus fills itself without agent cooperation, or
b) A seed mechanism that pre-populates the bus from existing project artifacts (git history, CLAUDE.md files, README, existing task lists), or
c) Deep integration with a specific agent host (Claude Code) so the behavior is on by default, not optional

The spec hints at all three but commits to none. That is what kills it.

---

## Summary Verdict

The core idea is sound: projects benefit from accumulated agent memory. The briefing concept is genuinely valuable. The SQLite append-only log is the right foundation.

But the spec has written a feature list in search of an adoption strategy. It adds semantic search before proving FTS5 is insufficient. It adds subscription infrastructure before proving agents will post events in the first place. It adds conflict detection before establishing the basic loop of post-then-query working reliably.

Build the briefing command first. Make it so good on day one — by seeding from git history, by generating a genuinely useful summary — that a developer who sees it once tells another developer. That is the only viable growth model for a local-first developer tool. Everything else in the spec is a distraction from that goal.

The right v1 spec is four pages. This one is eight.
