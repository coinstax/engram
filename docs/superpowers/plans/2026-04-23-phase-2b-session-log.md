# Phase 2b findings scratchpad (2026-04-23)

- Claude Code version: **2.1.118**
- Driving session branch: `v1.7-plugin` (3 commits ahead of origin)
- Sandbox: `/home/cdm/engram-test` (diverged from plan's `/tmp/engram-plugin-test-$DATE` — pragmatic choice)
- Active plugin warning to resolve at end: `evt-d9ae797ef0ce` (single event listing all four UNVERIFIED items)

## Baseline Engram event counts (real project DB `/home/cdm/engram/.engram/events.db`)

| event_type | count |
|---|---|
| decision   | 21 |
| discovery  |  8 |
| mutation   |  5 |
| warning    |  5 (1 active with scope plugin/, 4 others) |
| sessions   |  0 |

## Expected delta after Phase 2b
- +4 discoveries (one per unknown)
- +0 or +1 decision (if U1 fix applied)
- warning count unchanged (1 resolves but stays in table)
- sessions unchanged (we don't launch CC against the real repo in this session)

---

## Probe observations
(Each task appends its section here as it runs.)

### T3 — U1-E pre-test (engram-mcp honors ENGRAM_PROJECT_DIR)
- decoy env: `/tmp/engram-u1e-decoy`
- project_dir resolved to: `/tmp/engram-u1e-decoy` ✓
- events.db created at decoy path ✓
- **Result: PASS** — env var is honored; U1-E failure mode ruled out.

### T4 — S1 Plugin loads
- `/plugin list` shows: `engram Plugin · inline · ✔ enabled └ engram MCP · ✔ connected`
- No error annotation.
- **Result: PASS**

### T5 — S2 Skill discovered (partial)
- `/engram:briefing` exists in completion ✓
- Skill invocation shells out to `!engram briefing` ✓
- CLI responds: `Error: Engram not initialized in /home/cdm/engram-test. Run 'engram init' first.`
- **Result: skill wiring PASSES; blocked by missing `engram init` in sandbox.** This is not a skill defect — it's an engram precondition that the plugin does not auto-handle.

### T6 — S3 MCP + U1 diagnosis
- MCP connected: YES ✓
- Spawned cwd of plugin engram-mcp (PID 3022887): `/home/cdm/engram-test` ✓
- Env var on plugin engram-mcp: `ENGRAM_PROJECT_DIR=/home/cdm/engram-test` ✓  ← **${PWD} EXPANDED CORRECTLY**
- mcp__engram__status reported: `Engram isn't initialized in /home/cdm/engram-test. Run engram init first.` (consistent with T5 — same precondition)
- `.engram/` dir scan: no match in sandbox yet (expected; DB only exists after init + first insert)
- **U1 classification: U1-A** — plugin's `.mcp.json` `${PWD}` expansion works as assumed. Current `plugin/.mcp.json` is correct; no change needed.

### NEW DISCOVERY — plugin requires manual `engram init`

A new user installing the plugin via `/plugin install engram@coinstax/engram` would get "Engram not initialized" errors on first invocation until they manually run `engram init` in the project root. The plugin provides no auto-init. Options:

- **Option A — Document manually:** add to plugin/README.md: "After installing, run `engram init` in your project root."
- **Option B — Auto-init in SessionStart hook:** `hooks.py:handle_session_start` could detect missing `.engram/` and call `store.initialize()` silently. Side effect: implicit DB creation might surprise users. Also: `engram init` does `GitBootstrapper` seeding, which adds value — auto-init should probably include seeding too.
- **Option C — Auto-init on first skill invocation:** `/engram:briefing` skill could run `engram init` if not initialized. Awkward (skill has a side effect the user didn't ask for).

Defer the decision to Phase 3/4; for this verification session, run `engram init` manually to unblock.

### UNEXPECTED — two engram-mcp processes
- Plugin engram-mcp: CLAUDE_PLUGIN_ROOT set, ENGRAM_PROJECT_DIR=/home/cdm/engram-test (from ${PWD} expansion)
- Ambient engram-mcp: NO env vars — falls through to `os.getcwd()` which also resolves to `/home/cdm/engram-test`
- Both children of the sandbox `claude --debug --plugin-dir` process
- Both point at same DB (same project_dir) so responses are consistent.
- Source of ambient process: still unknown. Not `/home/cdm/engram/.mcp.json` (that would have set ENGRAM_PROJECT_DIR=/home/cdm/engram hardcoded, which it didn't). Likely some other user-level or implicit MCP registration we haven't traced. Non-blocking.
- Impact on Phase 2b: non-blocking for U1/U2/U3. For U2, only HOOKS are being tested, not MCP servers — the ambient MCP server doesn't install hooks.

### T8 — S4 SessionStart hook fires
- sandbox `.engram/events.db` exists (90KB) ✓
- sessions table: one active row `sess-1b76e20b | claude-code | Working on engram-test | 2026-04-23T20:59:57+00:00`
- **Result: PASS**

### T9 — S5 PostToolUse Edit hook fires
- Prompted Claude to add a line to README.md
- Mutation event: `mutation | claude-code | ["README.md"] | Wrote README.md (1 lines)`
- **Result: PASS**

### T10 — S6 PostToolUse Bash hook fires
- First attempt with `ls -la` produced NO outcome event (by design: `ls` is in `hooks.py:TRIVIAL_COMMANDS` skip list)
- Retry with `python -c 'print("hello from S6")'` — outcome event recorded: `Ran: python -c 'print("hello from S6")'`
- **Result: PASS** (test design note: use non-trivial bash commands for this probe)

### Baseline smokes summary
- S1 ✓ | S2 ✓ (with init precondition noted) | S3 ✓ (U1-A) | S4 ✓ | S5 ✓ | S6 ✓
- **All baseline smokes PASS.** U1 classification: A (no plugin code change needed).

### T12 — U2 Hook dedup (with CLI + plugin hooks both installed)
- plugin trace: 1 line
- cli trace: 1 line
- **Outcome: DOUBLE-FIRE** — both sources invoke independently per edit
- Secondary observation: only 1 mutation event in the DB (not 2), because `hooks.py:_handle_file_mutation` runs `_should_debounce()` at line 261 before insert. Engram's internal 5-second debounce catches the duplicate at the event layer.
- User impact: no duplicate events in the DB, but every tool use pays 2x hook-spawn latency (two shell invocations, two Python interpreter boots, two engram CLI loads).
- **Action per spec: DEFER.** v1.7.0 release notes must warn users who previously ran `engram hooks install` to run `engram hooks uninstall` first before installing the plugin. Phase 4 should teach the CLI installer to detect plugin presence and either skip or warn.

### T13 — U3 Skill pre-approves an MCP tool (pass 1, no permissions.allow)
- Q1 (loading): ✓ Skill loaded. `/test-mcp` appears in completion; `/engram:test-mcp` full form also works.
- Q2 (resolution): ✓ `mcp__engram__status` resolved and returned real data: `{project_name: "engram-test", total_events: 3, initialized_at: "2026-04-23T20:59:30", db_size_bytes: 90112}`.
- Q3 (prompt suppression without permissions.allow): ✓ **No permission prompt appeared.** Frontmatter `allowed-tools: mcp__engram__<tool>` is sufficient to pre-approve an MCP tool call from within a skill.
- **Result: CLEANEST OUTCOME.** Native MCP invocation from skills is viable as of Claude Code 2.1.118.

### T14 — U3 pass 2 (with permissions.allow)
- **Skipped.** Pass 1 produced a definitive answer (frontmatter alone is sufficient). Running pass 2 would redundantly confirm that adding `permissions.allow` also leaves the prompt suppressed. No new information.
- Implication for Phase 3+: skills can safely be rewritten to use native MCP calls instead of Bash shell-out to `engram`. Reduces latency and avoids double Python boot. Current `briefing/SKILL.md` is a candidate for migration in Phase 4.

### T15 — U4 Symlink survival across plugin cache copy
- Cache state: `~/.claude/plugins/cache/` has zero engram entries. `~/.claude/plugins/data/engram-inline/` exists but is empty.
- **Finding: `--plugin-dir` dev mode bypasses the cache-copy path entirely.** The plugin runs in-place from `/home/cdm/engram/plugin/`. No files are copied anywhere.
- Implication: for dev mode, symlink preservation is N/A (nothing is copied). For production install (marketplace or `/plugin install`), the question remains open — deferred beyond Phase 2b scope per fix-policy C (DEFER for U4).
- Did NOT create the test symlink — unnecessary given the above.

