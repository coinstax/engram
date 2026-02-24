# Consultation: P0 Feature Design: Event Lifecycle + Priority + Scope-Aware Briefings
- ID: conv-e0a5c4f6a8f1
- Models: gpt-4o, gemini-flash
- Status: completed
- Started: 2026-02-24T15:38:33.116144+00:00
- Updated: 2026-02-24T15:40:34.279015+00:00

## System Prompt
You are reviewing a design proposal for Engram, a local-first project memory system for AI coding agents. It stores structured events (decisions, discoveries, warnings, mutations, outcomes) in SQLite with FTS5 search and generates briefings that give agents context at session start. Current version is 1.2. The system has ~200 lines of briefing logic, ~290 lines of store logic, and 181 tests. Be specific and critical — point out edge cases, schema problems, and design flaws. Keep responses under 400 words.

---

## Turn 1

**host** (2026-02-24T15:38:33.118372+00:00):
I'm designing three P0 features that ship together because they all affect briefing output. Here's the plan:

**1. Event Lifecycle** — Add `status` column to events: active (default), resolved, superseded. New commands: `engram resolve <id> --reason '...'` and `engram supersede <id> --by <new-id>`. Briefings only show active events. Resolved/superseded remain queryable. Schema v4 adds `status TEXT DEFAULT 'active'` and `resolved_reason TEXT` and `resolved_by TEXT` (event ID that supersedes).

**2. Event Priority** — Add `priority` column: critical, high, normal (default), low. Briefings sort by priority within sections. Critical warnings always appear first. Schema v4 adds `priority TEXT DEFAULT 'normal'`.

**3. Scope-Aware Briefings** — Enhance briefing --focus <path> to rank events by relevance: exact scope match > parent dir match > unscoped. Show a 'Relevant to your focus' section at top. Global warnings always included. Recent events weighted higher.

All three go into a single schema v4 migration.

Questions I want your critique on:
- Is the status model right? Should 'resolved' and 'superseded' be separate states, or is one enough?
- Should priority be on all event types or only warnings/decisions?
- For scope-aware ranking, what's the right scoring formula?
- Are there edge cases or interactions between these three features I'm not seeing?
- Will this schema be forward-compatible with hierarchical summarization and conflict detection (planned for P1)?

**gpt-4o** (2026-02-24T15:38:33.119119+00:00):
Your design introduces meaningful enhancements, but there are areas that need careful consideration.

1. **Event Lifecycle**: Your `status` model seems appropriate, but consider clarity in distinguishing between "resolved" and "superseded." Both serve different purposes: "resolved" implies closure of the issue, while "superseded" indicates replacement. If these statuses were merged, you might lose granularity. Ensure your system logic clearly handles transitions between these states, particularly if a "superseded" event can ever become "resolved" or vice versa. Adding `resolved_reason` and `resolved_by` is good for traceability.

2. **Event Priority**: Applying priorities to all event types can add complexity without clear benefit for certain event types (e.g., discoveries or mutations). Limit priority to types that impact decision-making, like warnings and decisions. This will simplify both the user interface and the underlying logic.

3. **Scope-Aware Briefings**: For ranking, consider a scoring formula that combines scope relevance and recency linearly. You might use weighted coefficients: `Score = α * scope_relevance + β * recency`, where you adjust α and β through testing. Too much weighting on recent events could bury important older events.

4. **Edge Cases and Interactions**:
   - **Conflicting Events**: If an event with "superseded" status is marked as "critical," will its past importance force it into briefings despite being superseded?
   - **Complex Resolutions**: How do you handle events superseded by multiple other events, or those resolved and then reopened?
   - **Scope Overlap**: An event that pertains to multiple scopes could be ranked inconsistently if based solely on directory matching.

5. **Forward-Compatibility**:
   - Your current schema seems adaptable to hierarchical summarization. You might want to include parent-child relations explicitly in the schema to facilitate this.
   - For conflict detection, consider how the system will identify and handle contradictory statuses or priorities among related events.

By addressing these considerations, you can better align the enhancements with robust future expansions without introducing complexity that could cause unforeseen issues.

**gemini-flash** (2026-02-24T15:38:33.119119+00:00):
Here's a critical review of your P0 features:

**1. Event Lifecycle (`status`, `resolved_reason`, `resolved_by`):**
*   **Schema Flaw:** `resolved_by TEXT` is confusing. It should be `superseded_by_event_id TEXT` as it links to the *superseding* event. `resolved_reason TEXT` is appropriate for `resolved` events. Consider if `superseded` events also need a `superseded_reason TEXT`.
*   **Model:** Separating `resolved` and `superseded` is correct. They represent distinct semantic outcomes. `resolved` means a problem is fixed; `superseded` means an event has been replaced.
*   **Edge Case:** If a superseding event itself gets superseded, your `superseded_by_event_id` field only tracks the immediate predecessor. This is generally fine, but be aware it doesn't build a full lineage chain directly.

**2. Event Priority (`priority`):**
*   **Scope:** Applying `priority` to *all* event types is a good design choice. While its immediate briefing impact might be on warnings/decisions, a "critical discovery" or "low-priority mutation" could be meaningful for future features or deeper analysis. This offers flexibility without adding schema complexity later.
*   **Clarity:** Sorting by priority within sections and critical warnings always appearing first is clear.

**3. Scope-Aware Briefings (`--focus` ranking):**
*   **Scoring Formula:** This needs a explicit definition to avoid ambiguity.
    1.  **Hard Filter:** `active` events only (from Lifecycle). `global` warnings are always included, irrespective of focus (they form a top section).
    2.  **Categorization:** Group remaining `active` events into 'Exact Match', 'Parent Directory Match', 'Unscoped'.
    3.  **Weighting & Sorting:**
        *   Assign a base weight (e.g., Exact: 3, Parent: 2, Unscoped: 1).
        *   Add a recency bonus: `score += f(time_since_event_creation)`. Ensure `f` decays over time (e.g., `max(0, 1 - (days_old / 30)) * X_bonus`).
        *   Final sort: By total score (desc), then by `priority` (critical > high > normal > low), then by creation timestamp (desc).
*   **Edge Case:** What about events scoped to sibling directories (e.g., `--focus src/foo` and an event is `src/bar`)? Your current plan only covers parents. This might be fine for P0 but is a potential future nuance.

**Interactions & Edge Cases:**
*   **Critical Priority + Scope:** Clarify "Critical warnings always appear first." Does this mean *globally* first, even if not focus-relevant, *before* the 'Relevant to your focus' section? Or first *within* their relevance group? The former (`global` placement) seems implied and is a reasonable, strong signal.
*   **Recency + Lifecycle:** Only `active` events are ranked by recency. Correct.
*   **Priority + Lifecycle:** An event losing its `active` status means its priority no longer matters for briefings. Correct.

**Forward Compatibility (P1):**
*   **Lifecycle:** `resolved` and `superseded` states, especially with `superseded_by_event_id`, are excellent for hierarchical summarization (tracing event lineage) and conflict detection (identifying which events are the current source of truth).
*   **Priority:** Essential for prioritizing summaries (e.g., 'summarize high-priority active issues') and flagging critical conflicts.
*   **Scope:** Crucial for hierarchical summarization (summarizing within a particular file/directory) and localized conflict detection.
*   **Schema (re-emphasized):** Renaming `resolved_by` to `superseded_by_event_id` is critical for clarity and accuracy, especially when building P1 features that rely on event relationships. This `TEXT` field is implicitly a foreign key and will be vital for graph-like traversals.

---

## Turn 2

**host** (2026-02-24T15:39:18.648595+00:00):
Good critiques. Let me respond and push further:

1. **Schema naming** — Gemini is right. I'll rename to `superseded_by_event_id` for clarity. And I'll keep `resolved_reason` separate from superseding — they're different operations.

2. **Priority scope** — You disagree here. GPT says limit to warnings/decisions, Gemini says apply to all types. I'm leaning toward Gemini's take: the column exists on all rows anyway (it's a TEXT DEFAULT 'normal'), and a 'critical discovery' is a real thing. The cost of having it on mutations is zero if nobody sets it. Agree?

3. **Scoring formula** — Gemini's proposal is concrete: base weight (exact:3, parent:2, unscoped:1) + recency bonus with 30-day decay + sort by score then priority then timestamp. But I'm worried about over-engineering. Would a simpler approach work: just partition into 3 groups (focus-relevant, global warnings, other) and sort by priority+recency within each group? No floating-point scoring, just grouping.

4. **Critical + Scope interaction** — To clarify my intent: critical warnings ALWAYS appear at the very top of the briefing regardless of scope. They're 'you must know this' items. Everything else follows scope-aware ranking. This means a critical warning about database corruption shows up even if you're focused on the CSS layer.

5. **New concern** — When I resolve/supersede an event, should the briefing mention it once? e.g., 'Resolved: JWT expiry warning (fixed in PR #42)'. This gives agents confidence that known issues were handled, rather than silently hiding them. But it could get noisy. Thoughts on a 'recently resolved' section that only shows resolutions from the last 24-48h?

**gpt-4o** (2026-02-24T15:39:18.650532+00:00):
Your clarifications and extensions bring several improvements and raise insightful questions. Here's how you might proceed:

1. **Schema Naming**: Renaming to `superseded_by_event_id` is a wise choice for clarity, especially given its potential role in future hierarchical summarization.

2. **Priority Scope**: You're right to lean towards Gemini's perspective. Having a priority column universally allows more flexible prioritization without significant downsides. The capability to mark any type as "critical" can be useful for edge cases and future expansions.

3. **Scoring Formula**: A simpler scoring approach could indeed avoid over-engineering while achieving clarity:
   - **Partition into Groups**: Divide events into three groups: critical warnings, focus-relevant events, and others.
   - **Sort by Priority and Recency**: Within each group, simply sort events by priority first and then recency. This removes the need for floating-point calculations and maintains readability.
   
   Using a partitioned approach makes it clear and straightforward, which is often better for maintainability and understandability among users.

4. **Critical + Scope Interaction**: Your clarified approach makes sense and is consistent with the “must know” nature of critical warnings. Placing them at the top of the briefing ensures immediate visibility and actionability, aligning with your intent of prioritizing crucial information.

5. **Recently Resolved Section**: Introducing a "Recently Resolved" section limited to the last 24-48 hours is a logical addition. It provides closure on issues without overwhelming the main briefing content. This aligns with maintaining transparency about system changes and aiding agents in understanding which problems have been handled recently.

In summary, your refined design considerations strike a balance between visibility, relevance, and manageability, which are crucial in a memory system for AI agents. Your approach to partitioning and prioritization maintains the essence without complicating the logic unnecessarily. Ensure thorough testing of your simpler system to confirm it meets your goals without unnoticed drawbacks.

**gemini-flash** (2026-02-24T15:39:18.650532+00:00):
Okay, excellent responses and clarifications. Let's refine further.

1.  **Schema Naming (`superseded_by_event_id`)**: Good call. This clarifies intent and aids future schema comprehension and relational queries. Keeping `resolved_reason` separate is also correct; they capture different types of closure.

2.  **Priority Scope (All Event Types)**: I agree with your leaning towards Gemini's take. The minimal cost of a `DEFAULT 'normal'` column on all events is far outweighed by the flexibility. A "critical discovery" or "low-priority mutation" could indeed be meaningful, especially as Engram evolves, providing a future-proof hook for nuanced analysis.

3.  **Scoring Formula (Simplified Grouping)**: Your intuition to simplify is sound. Instead of a complex floating-point score, a tiered grouping approach is often more robust and easier to reason about:
    1.  **Critical Warnings:** Always at the top (as clarified below).
    2.  **Focus-Relevant:** Events with exact or parent directory matches to the `--focus` path.
    3.  **Global Warnings:** Non-critical warnings not specifically tied to the focus.
    4.  **Other/Unscoped:** All remaining active events.
    Within each of these tiers, sort first by `priority` (critical > high > normal > low), then by `recency` (newest first). This avoids arbitrary weights and provides a clear, understandable hierarchy.

4.  **Critical + Scope Interaction**: Your clarification that critical warnings *always* appear at the very top is clear and effective. It ensures "must-know" items are never missed, even when the agent is deep in a specific code focus. This is a strong design choice for safety and awareness.

5.  **New Concern (Recently Resolved Section)**: This is a **great idea**. Silently removing resolved events can indeed erode trust or leave agents wondering if an issue was addressed. A "Recently Resolved" section (e.g., last 24-48 hours) provides transparency without overwhelming the briefing. It gives agents confidence that problems are being actively managed. This is a valuable addition to the briefing output.

---

## Turn 3

**host** (2026-02-24T15:39:56.293132+00:00):
Good, we're converging. Let me propose the final design and get your sign-off or last objections.

**Schema v4 migration — 3 new columns on events table:**
```sql
ALTER TABLE events ADD COLUMN status TEXT DEFAULT 'active' CHECK(status IN ('active','resolved','superseded'));
ALTER TABLE events ADD COLUMN priority TEXT DEFAULT 'normal' CHECK(priority IN ('critical','high','normal','low'));
ALTER TABLE events ADD COLUMN resolved_reason TEXT;
-- superseded_by uses existing related_ids convention: when superseding, the new event's related_ids includes the old event's ID, and the old event's status is set to 'superseded'. No extra column needed.
```

Wait — actually, I realize I can simplify. Instead of a separate `superseded_by_event_id` column, the superseding relationship is already captured by the new event's `related_ids` pointing to the old one. When you run `engram supersede evt-old --by evt-new`, it just sets evt-old's status to 'superseded' and ensures evt-new's related_ids includes evt-old. The link is in the related_ids graph. Does this work, or do I need a dedicated column for reverse lookup efficiency?

**Briefing output structure:**
```
# Engram Briefing — project-name
## Critical Warnings (always shown)
  [critical warnings regardless of scope]

## Relevant to src/auth/ (focus)
  ### Warnings [sorted by priority, then recency]
  ### Decisions
  ### Recent Changes
  ### Discoveries

## Other Active Items
  [remaining active events not matching focus]

## Recently Resolved (last 48h)
  [resolved/superseded events with reason, limited to 5-10 items]
```

**CLI changes:**
- `engram resolve <id> --reason '...'` — sets status=resolved
- `engram supersede <id> --by <new-id>` — sets status=superseded, links via related_ids
- `engram post` gets `--priority` flag (default: normal)
- `engram briefing` gets `--focus` flag

**What I'm NOT doing:**
- No floating-point scoring — just group + sort
- No separate index for priority — table is small enough for scan
- No reopening of resolved events — if a resolved issue recurs, post a new event

Final objections?

**gpt-4o** (2026-02-24T15:39:56.294654+00:00):
Your refined design is well thought-out and addresses initial concerns effectively. Here's the final assessment:

1. **Schema v4 Migration**:
   - **Column Design**: Your decision to use `related_ids` for maintaining the supersession link is pragmatic and aligns with existing design principles. If `related_ids` can already capture the relationship effectively, then a separate `superseded_by_event_id` column may be unnecessary, particularly given the small table size. However, be aware that queries exploring complex historical relationships might be slightly less efficient without a dedicated reverse lookup column. This trade-off is acceptable for your current scope, assuming usability in real-world query scenarios remains manageable.

2. **Briefing Output Structure**:
   - **Clarity and Usability**: This structure is clear and user-friendly, effectively prioritizing critical information and addressing concerns about visibility and focus. The separation into sections enhances comprehension.
   - **Recently Resolved Section**: Limiting to items from the last 48 hours balances utility with noise reduction well.

3. **CLI Changes**:
   - **Logical Additions**: The new commands and flags are intuitive and align well with the intended functionalities. The explicit separation of `resolve` and `supersede` contributes to simplicity and clarity in user operations.
   - **Priority Flag**: Offering a `--priority` flag for `engram post` aligns with the general approach of prioritization, maintaining coherence in interactions.

4. **Deferred Features**:
   - **Decision to avoid complex scoring and indices**: Your simpler approach matches the project's current scale and anticipated data volume. The focus on grouping and sorting based on logical attributes is suitable.
   - **Reopening Resolved Events**: Handling recurring issues with new events maintains clean historical tracking while avoiding complex state management.

In conclusion, your proposal achieves a robust balance between functionality, simplicity, and future extensibility without sacrificing present-day performance or usability. Ensure comprehensive testing, especially around how `related_ids` handles complex event histories and necessary indexes for search efficiency. If future growth impacts performance, consider more sophisticated indexing strategies or reverse reference implementations. For now, your design looks solid and well-aligned with project goals. Proceed with confidence!

**gemini-flash** (2026-02-24T15:39:56.294654+00:00):
Okay, this is a very well-rounded and detailed design. We're largely converged, and your simplifications are intelligent.

I have one final, significant objection, which is a re-emphasis of my prior point:

**1. `superseded_by_event_id` vs. `related_ids` for Reverse Lookup**
Relying solely on `related_ids` for the "superseded by" link is a **design flaw** for efficiency and clarity.

*   **Inefficient Reverse Lookup:** If you have `evt-old` with `status='superseded'`, and you need to know *what* event superseded it, you would have to scan `related_ids` across *all* active events to find an event whose `related_ids` list contains `evt-old`'s ID. This will be an expensive operation.
*   **Ambiguity:** `related_ids` is generic. Does every ID in `related_ids` imply a superseding relationship, or just a general link? A dedicated `superseded_by_event_id` column on the `evt-old` row explicitly states "this specific event superseded me."
*   **Future Complexity:** For P1 features like hierarchical summarization or conflict detection, you'll frequently want to traverse the supersession graph efficiently. A dedicated, indexed column (`superseded_by_event_id` on the *superseded* event, pointing to the *superseding* event) makes this trivial. Without it, you're building an implicit, hard-to-query relationship.

**Recommendation:** Revert to including `superseded_by_event_id TEXT` on the `events` table. When `engram supersede evt-old --by evt-new` is called:
1.  `evt-old.status` is set to `'superseded'`.
2.  `evt-old.superseded_by_event_id` is set to `evt-new.id`.
3.  (Optional, but good for completeness): `evt-new.related_ids` is updated to include `evt-old.id`.

This ensures direct, efficient lookup from the superseded event to its superseder.

---

**Aside from that crucial point, your design looks solid:**

*   **Schema:** The `status` and `priority` columns with `CHECK` constraints are excellent.
*   **Briefing Output Structure:** This is clear, logical, and addresses all requirements, including the "Critical Warnings always at top" and "Recently Resolved" sections.
*   **CLI Changes:** Consistent and intuitive.
*   **"What I'm NOT doing":** These are all pragmatic and sensible decisions for initial implementation. No floating-point scoring, no specific priority index (for now), and no re-opening of resolved events all make sense for project simplicity and maintainability.

The only remaining friction point is the `superseded_by_event_id` column. Address that, and you'll have a robust and well-thought-out P0.

---

## Summary
Consensus on P0 design: 3 features ship together in schema v4. GPT-4o validated simplified grouping over float scoring, agreed on recently-resolved section. Gemini caught key flaw: superseded_by needs dedicated column for reverse lookup efficiency, not just related_ids. Both agreed priority should apply to all event types. Final schema: status, priority, resolved_reason, superseded_by_event_id columns.
