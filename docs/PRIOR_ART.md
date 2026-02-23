# AgentBus — Prior Art & Competitive Landscape

Research conducted: 2026-02-23

## Direct Competitors / Overlapping Projects

### Mem0 — Universal Memory Layer for AI Agents
- **URL**: https://github.com/mem0ai/mem0
- **What it does**: Persistent memory layer that extracts, evaluates, and manages salient information from conversations. Has a graph variant (Mem0g) that stores memories as directed labeled graphs.
- **Overlap**: Persistent memory, cross-session context
- **Gap it doesn't fill**: No inter-agent communication, no event bus, no conflict detection, no real-time coordination. It's memory for a *single* agent, not a *coordination layer* between agents.
- **Takeaway**: We should study their memory extraction and relevance scoring. But our scope is fundamentally different — we're building coordination infrastructure, not just memory.

### Memori — Open-Source Memory Engine
- **URL**: https://www.opensourceprojects.dev/post/1989226046231867591
- **What it does**: Backend service as a long-term memory bank. Stores memories (facts, events, conversations) in a structured, searchable way.
- **Overlap**: Persistent searchable memory
- **Gap**: Same as Mem0 — single-agent focused, no bus/coordination semantics.

### MassGen — Multi-Agent Scaling System
- **URL**: https://github.com/massgen/MassGen
- **What it does**: Coordinates AI agents through redundancy and iterative refinement. Agents vote on best answers.
- **Overlap**: Multi-agent coordination
- **Gap**: Focused on consensus/voting on outputs, not on persistent project knowledge or file-level coordination. Different problem domain.

### Microsoft Agentic Framework (MAF)
- **What it does**: SDK with asynchronous message bus for cooperating software agents. Scales across Azure/K8s.
- **Overlap**: Message bus concept
- **Gap**: Enterprise/cloud-focused, heavy infrastructure. Not local-first, not designed for developer tooling agents.

## Inter-Agent Communication Protocols

### Model Context Protocol (MCP)
- **By**: Anthropic
- **Focus**: Connecting AI agents with external tools and resources
- **Relevance**: AgentBus should expose an MCP interface. MCP is the de facto standard for Claude Code tool integration. But MCP itself is a tool *protocol*, not a coordination *system*.

### Agent2Agent Protocol (A2A)
- **By**: Google, now Linux Foundation
- **Focus**: Interoperability between agents from different providers
- **Relevance**: A2A treats agents as opaque — they collaborate without revealing internals. Good design principle we should adopt. But A2A is a *protocol spec*, not a running system.

### Agent Communication Protocol (ACP)
- **By**: IBM Research (BeeAI)
- **Focus**: REST-native framework for interoperable agents
- **Relevance**: Layered architecture is well-designed. But ACP is about agent-to-agent RPC, not about shared persistent project state.

### Agent Network Protocol (ANP)
- **Focus**: Cross-platform agent collaboration over open internet
- **Relevance**: Decentralized identity, semantic web. Interesting for future cross-project features but overkill for local developer agent coordination.

## Orchestration Frameworks

### LangGraph
- Graph-based agent design, conditional logic, multi-team coordination
- **Gap**: Orchestration focused — defines how agents execute, not how they share knowledge

### AutoGen (Microsoft)
- Multi-agent message passing in loops
- **Gap**: Conversation-centric, not project-state-centric

### CrewAI
- Role-based multi-agent coordination
- **Gap**: Task execution framework, not a memory/coordination layer

## Research Papers of Interest

- "Multi-agent In-context Coordination via Decentralized Memory Retrieval" (Nov 2025)
- "MemEvolve: Meta-Evolution of Agent Memory Systems" (Dec 2025)
- "Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory" (2025)
- Survey: "Agent Interoperability Protocols: MCP, ACP, A2A, ANP" (arxiv 2505.02279)

## Where AgentBus Fits

**AgentBus occupies a unique position**: it's a *local-first, project-scoped, developer-agent-focused* coordination + memory layer. Nothing in the current landscape combines:

1. Event bus semantics (structured events, subscriptions, conflict detection)
2. Persistent semantic memory (embeddings, lessons learned)
3. Project-scoped context (file paths, git awareness)
4. Agent-agnostic interface (CLI + HTTP + MCP)
5. Zero infrastructure (SQLite, no cloud, no servers)

The closest thing would be combining Mem0 (memory) + A2A (communication) + a custom conflict detector, but that's three separate systems with no local-first story.

## Design Implications

1. **Adopt MCP as a first-class interface** — it's the standard Claude Code and other tools use
2. **Study Mem0's memory extraction patterns** — their relevance scoring is mature
3. **Borrow A2A's opacity principle** — agents don't need to expose internals
4. **Don't reinvent orchestration** — AgentBus coordinates, it doesn't orchestrate. Let LangGraph/CrewAI handle workflow.
5. **SQLite is the right call** — local-first, zero-config, concurrent-safe with WAL mode
6. **Embeddings must be local** — can't depend on API calls for core search functionality

## Sources
- [Mem0 GitHub](https://github.com/mem0ai/mem0)
- [MassGen GitHub](https://github.com/massgen/MassGen)
- [Awesome-Memory-for-Agents (Tsinghua)](https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents)
- [Top 5 Open Protocols for Multi-Agent AI](https://onereach.ai/blog/power-of-multi-agent-ai-open-protocols/)
- [Agent Interoperability Protocols Survey](https://arxiv.org/html/2505.02279v1)
- [A2A Protocol — Google](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/)
- [ACP — Towards Data Science](https://towardsdatascience.com/acp-the-internet-protocol-for-ai-agents/)
- [AWS on MCP Inter-Agent Communication](https://aws.amazon.com/blogs/opensource/open-protocols-for-agent-interoperability-part-1-inter-agent-communication-on-mcp/)
- [Mem0 Paper](https://arxiv.org/pdf/2504.19413)
- [AI Coding Agents 2026 — Mike Mason](https://mikemason.ca/writing/ai-coding-agents-jan-2026/)
