# Engram v1.1 Consultation: GEMINI
Date: 2026-02-23T14:42:43.363550
Model: gemini-2.5-flash

---

Alright, let's cut to the chase. I've reviewed Engram v1.0 and your v1.1 roadmap. While v1.0 is a solid foundation – credit where credit is due for solving the cold start and getting a minimal viable product out – it's still largely a *manual logbook*. The core problem remains: **high activation energy for agents, leading to low compliance.** If agents aren't writing to it, it's just a fancy `grep` on a partial history. We need to move beyond a glorified `print` statement.

My previous recommendations for semantic search and hierarchical summarization are still glaring omissions, and the v1.1 roadmap, while hitting some good points, doesn't go far enough in addressing the *intelligence* and *automation* required for a truly useful project memory system.

Here's my direct critique and suggestions:

---

### 1. The v1.1 features listed above -- Are these the right priorities? What's missing? What should be cut or deferred? Rank them by impact.

Let's be clear: the existing roadmap is necessary but insufficient.

1.  **Passive Observation:** **CRITICAL. Absolute Top Priority.** This is *the* unlock. Without it, Engram remains a manual chore. It directly addresses the "high activation energy, low compliance" problem. It's not just about mutation events; it's about *any* observable activity. This is the single biggest blocker to adoption and usefulness.
2.  **CLAUDE.md Auto-Generation:** **High Impact, Easy Win.** This is a no-brainer. Reduces friction for initial setup, reinforces the tool's presence. Should have been in v1.0. Implement this immediately.
3.  **Stale Assumption Detection:** **High Impact, but dependent on other features.** This is a critical step towards "briefing intelligence" and "stale assumption detection" (gap #3). It *requires* robust event linking/referencing and potentially more sophisticated event content analysis. It's a key feature, but might be a stretch for v1.1 if passive observation isn't fully robust *and* event linking isn't in place. **If passive observation and event linking are solid, then this becomes a very high priority.**
4.  **Compact Output Improvements:** **Low Impact, Defer.** While token efficiency is good, the *quality* and *relevance* of the output matter far more than shaving off a few tokens. If the output is irrelevant or overwhelming, it doesn't matter how compact it is. Focus on what gets *into* Engram and how it's *summarized* first. This is a premature optimization.

**Ranked Impact for v1.1:**
1.  **Passive Observation (Absolute Must-Have)**
2.  **CLAUDE.md Auto-Generation (High UX Impact, Easy Win)**
3.  **Event Linking/Referencing (Foundational for intelligence, needs to be added to roadmap)**
4.  **Stale Assumption Detection (High Impact, but dependent on 1 & 3)**
5.  **Compact Output Improvements (Defer. Focus on content quality and intelligence first.)**

**What's missing from the v1.1 roadmap (that should be in it):**
*   **Event Linking/Referencing:** This is foundational for any form of intelligence (staleness, hierarchical summarization, causality). It's a critical enabler.
*   **Initial steps towards Hierarchical Summarization:** The current briefing is flat. Even basic grouping or summarization of *related* passive events would be a huge win. This doesn't need full LLM intelligence yet, but can start with heuristics.
*   **"Assumption" Event Type:** Explicitly defining assumptions is necessary for robust stale assumption detection.

---

### 2. The passive observation problem -- How should it work concretely?

This is the hardest and most important feature. We need a hybrid approach, prioritizing **agent-centric observation** over raw system-level monitoring. The goal is to capture *intent* and *context*, not just raw changes.

**My Recommended Approach for v1.1: A Smart MCP Tool Wrapper (Primary) with a File Watcher (Secondary/Validation).**

1.  **Primary: Robust, Intelligent MCP Tool Wrapper (`engram.tool_wrapper`).**
    *   **Concept:** This isn't just for file writes. It's a wrapper for *any significant agent action* that interacts with the project environment. Agents should be instructed to wrap their calls to common tools like `write_file`, `run_command`, `read_file`, `search_code`, etc., with this `engram.tool_wrapper`.
    *   **Mechanism:** The wrapper intercepts the tool call, logs a `decision` or `discovery` event *before* execution (e.g., "Agent decided to write to `foo.py`"), executes the actual tool, then logs an `outcome` or `mutation` event *after* execution (e.g., "File `foo.py` was modified successfully" or "Command `pytest` failed with error...").
    *   **Event Generation:**
        *   `write_file(path, content)`: Pre-execution: `decision: write_file to {path}`. Post-execution: `mutation: file {path} changed`. The `content` of the `mutation` event could be a concise diff or a summary of the change.
        *   `run_command(command)`: Pre-execution: `decision: run_command '{command}'`. Post-execution: `outcome: command '{command}' exited with code {return_code}`. Include stdout/stderr in `content` up to the cap.
        *   `read_file(path)` / `search_code(query)`: Pre-execution: `discovery: reading {path}` / `discovery: searching for '{query}'`. Post-execution: `outcome: read {path} (first N chars)` / `outcome: search found M results`.
    *   **Benefits:** Captures agent *intent* and *action-result pairs*, which are infinitely more valuable than just "file changed." It ties events directly to the agent's observable behavior.
    *   **Implementation:** The `engram` CLI could expose a `engram tool-proxy` command that takes a tool name and arguments, logs, executes, and logs again. Or, provide a Python library function `engram.wrap_tool(tool_func, event_type_pre, event_type_post)` that agents can use.

2.  **Secondary: Lightweight File System Watcher (for validation and catch-all).**
    *   **Concept:** A background `fswatch` daemon runs *during* an agent session, monitoring the project directory.
    *   **Mechanism:** It doesn't primarily *generate* events. Its main role is to **detect discrepancies** and **unattributed changes**. If the MCP wrapper *should* have logged a file change but the watcher sees one that wasn't logged, it's a flag. This helps identify agent bypasses, external changes (e.g., user intervenes), or issues with the wrapper.
    *   **Event Generation:** If a change is detected that *cannot* be attributed to a recently logged agent action, it generates a generic `mutation:unattributed` event, perhaps with a warning flag, including the file path and a hash of the change.
    *   **Benefit:** Provides a safety net and helps ensure data completeness, even if not perfectly attributed.

3.  **Tertiary: Git Diff (for session-end summary).**
    *   **Concept:** At the end of a session (or `engram stop`), run a `git diff --name-only` or similar to get a summary of all changed files.
    *   **Mechanism:** Generate a single `outcome:session_summary` event listing all files changed during the session, potentially with a link to the `git diff` output itself.
    *   **Benefit:** Provides a high-level summary/checkpoint of the session's impact, useful for auditing or reviewing major work units.

**Why this combination?** The MCP tool wrapper gives us high-quality, attributed, intent-driven events. The file watcher provides a robust catch-all. Git diff provides a clean session summary. This maximizes the signal-to-noise ratio in Engram.

---

### 3. Event linking and references -- Should v1.1 add the ability to link events?

**YES. This is absolutely critical for any meaningful intelligence and should be a v1.1 priority.**

**How complex should this be?** Start simple but design for future extensibility.

*   **New Field: `related_event_ids` (List of IDs).** Add an optional field, `related_event_ids`, which is a JSON array of integers (Engram `id`s). This allows an event to reference one or more other events.
*   **Schema Change:** `related_event_ids TEXT` (stored as JSON string) in SQLite.
*   **Agent Instruction:** Agents should be instructed to use this.
    *   A `mutation` event (e.g., "file changed") should ideally link back to the `decision` event that prompted it.
    *   An `outcome` event (e.g., "tests passed") should link back to the `decision` or `mutation` events it evaluates.
    *   A `warning` event (e.g., "dependency conflict") might link to the `decision` that introduced the dependency.
*   **Passive Observation Integration:** The intelligent MCP tool wrapper should automatically infer and add `related_event_ids`. For example, a `mutation` event generated after a `decision: write_file` should automatically link to that `decision` event. This will require some simple context tracking within the wrapper (e.g., "last `decision` event for this agent").

This simple linking provides the fundamental graph structure needed for sophisticated analysis: causality, staleness, and hierarchical summarization.

---

### 4. Briefing intelligence -- How should it get smarter?

The current briefing is a dumb list. We need to move towards my original recommendation of **hierarchical summarization** and **semantic understanding** (even if heuristic-based for v1.1).

**v1.1 Steps for Smarter Briefing:**

1.  **Leverage Event Linking for Grouping & Contextualization:**
    *   **Causal Chains:** If events are linked (e.g., `decision` -> `mutation` -> `outcome`), the briefing should present these as a single logical unit. Instead of listing 5 individual `mutation` events, it should say "Decision X led to 3 file changes and outcome Y."
    *   **Contextual Warnings:** When showing a `warning`, if it's linked to a `decision` or `mutation`, the briefing should mention this: "Warning Z related to Decision X (to add feature Y)."

2.  **Basic Deduplication & Aggregation (Heuristic-based):**
    *   **Similar Mutations:** If multiple `mutation` events occur very close in time affecting the same file or with very similar content (e.g., multiple editor saves), collapse them into a single, more general `mutation` event in the briefing (e.g., "File `foo.py` was modified several times between T1 and T2").
    *   **Repeated Warnings/Discoveries:** If the same `warning` or `discovery` event (same content, same scope) occurs multiple times within a window, show it once with a count, or just the latest instance. Use content hashing (see new ideas) for this.

3.  **Staleness Detection Integration:**
    *   If a `decision` or `assumption` is flagged as stale by a subsequent `mutation` event (using the new v1.1 feature), the briefing must prominently display this. "Decision X (STALE: invalidated by mutation Y)." This is paramount for preventing agents from operating on outdated information.

4.  **Priority Scoring (Simple Heuristics):**
    *   Initially, assign priority based on event type (e.g., `warning` > `assumption` (if not stale) > `decision` (if not completed) > `mutation` > `discovery` > `outcome`).
    *   The briefing should present higher priority items first, or highlight them.

**Crucially, the briefing should be *summarizing* clusters of events, not just listing them.** For v1.1, this can be done with simple Python logic, not necessarily an LLM *within* Engram yet. The goal is to provide a more structured and intelligent input for the *consuming LLM agent* to then summarize further.

---

### 5. What's the single highest-impact thing we could build for v1.1?

**Robust, Agent-Centric Passive Observation with Intent-Driven Event Generation (as detailed in point 2).**

This is the absolute linchpin. If agents don't automatically populate Engram with high-quality, contextualized events, it will remain a manual burden and fail to achieve its potential as a project memory. The "MCP tool wrapper" approach, intelligently generating linked events, is the path. This single feature unlocks everything else: a richer log for stale assumption detection, better input for future summarization, and a dramatically lower cognitive load for the agent. Without it, the rest are just enhancements to an empty or sparsely populated log.

---

### 6. What should we explicitly NOT build yet?

1.  **Full-blown Semantic Search (using embeddings/vector DB):** While I previously advocated for it, v1.0's F