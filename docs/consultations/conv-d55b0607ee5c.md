# Consultation: Engram v1.3 feature planning
- ID: conv-d55b0607ee5c
- Models: gpt-4o
- Status: completed
- Started: 2026-02-24T06:05:41.130679+00:00
- Updated: 2026-02-24T06:06:20.335046+00:00

---

## Turn 1

**host** (2026-02-24T06:05:41.138453+00:00):
I'm the developer of Engram, a local-first project memory system for AI coding agents. We just shipped v1.2 with multi-turn consultations. For v1.3, I'm considering: (1) semantic search with embeddings to replace FTS5, (2) hierarchical summarization to compress old events, (3) a subscription/notification system so agents get alerted to relevant new events. Which would you prioritize and why? Keep your response under 300 words.

**gpt-4o** (2026-02-24T06:05:41.139356+00:00):
For the next release, prioritizing (1) semantic search with embeddings could have the most immediate and significant impact on usability and system performance. Replacing FTS5 with a more advanced semantic search can enhance the way agents retrieve information, making searches more intuitive and context-aware. This change can help agents better understand and utilize stored information, significantly improving the overall effectiveness of your project memory system.

Semantic search using embeddings allows for more natural language queries and can retrieve results based on meaning rather than keyword matching. This capability would enable users to interact with the memory system in a more human-like manner, potentially increasing productivity and satisfaction. Furthermore, it lays the groundwork for further improvements that can leverage the understanding of natural language and contextual relevance.

Hierarchical summarization (2) is also important for maintaining efficiency as information grows over time. However, this can be approached incrementally or in tandem as part of a longer-term strategy to ensure the system remains scalable. It might not have as immediate an impact as upgrading the search capabilities.

Lastly, a subscription/notification system (3) could be highly beneficial in keeping agents informed of relevant developments but might not be as foundational as improving search efficiency and accuracy. It can be integrated more effectively once the system's retrieval capabilities are robust and capable of interpreting user needs through advanced search functions.

By enhancing search first, you ensure a solid, user-friendly foundation for future improvements, whether those are in event summarization or notification systems.

---

## Turn 2

**host** (2026-02-24T06:05:57.627553+00:00):
Interesting take, but I disagree about semantic search. FTS5 is sufficient for <10k events with zero dependencies. Embeddings would add heavy deps (sentence-transformers, torch) and complexity. What about hierarchical summarization instead? It solves the real scaling problem: context window limits when generating briefings from thousands of events. Keep under 200 words.

**gpt-4o** (2026-02-24T06:05:57.629987+00:00):
Given your context, prioritizing (2) hierarchical summarization makes a lot of sense. As your system scales to thousands of events, maintaining an efficient way to compress and summarize past information becomes crucial. Hierarchical summarization addresses the core issue of context window limits, enabling the generation of concise briefings without overwhelming the available memory of the AI when processing large event histories.

Effective summarization helps in distilling essential information from vast data sets, allowing agents to focus on key insights and trends without sifting through noise. This not only enhances performance but also facilitates more accurate and contextually relevant decision-making by the agents.

Additionally, since your current search system (FTS5) is adequate for smaller datasets and avoids dependencies, focusing on summarization overhauls manages growth effectively while keeping the system lightweight and efficient. This ensures long-term scalability without introducing complex new technologies and dependencies.

Implementing hierarchical summarization first aligns with your goals and use cases, solving the pressing problem of managing and utilizing exponentially growing event data efficiently.

---

## Summary
GPT-4o initially favored semantic search, but agreed hierarchical summarization is the right v1.3 priority given zero-dep philosophy and real scaling bottleneck (briefing context limits)
