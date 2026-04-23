# Phase 2b — Plugin Verification Test Procedure

**Status:** Draft (pre-execution)
**Target branch:** `v1.7-plugin`
**Target release:** v1.7.0
**Author:** Engram maintainer + assistant (brainstorming session 2026-04-23)

## Purpose

Verify four Claude Code plugin behaviors whose live behavior the documentation does not pin down. These are currently recorded as HIGH warnings in Engram (posted 2026-04-21). Until they are resolved, the v1.7.0 plugin rests on assumptions.

The four unknowns:

1. **`${PWD}` expansion in `.mcp.json` env vars** — does Claude Code expand `${PWD}` in an MCP server's env block?
2. **Hook merge/dedup** — when a user's `.claude/settings.json` and a plugin's `hooks/hooks.json` both register identical PostToolUse commands, do both fire?
3. **Skill can pre-approve an MCP tool** — does `allowed-tools: mcp__engram__status` in a SKILL.md frontmatter pre-approve the MCP tool?
4. **Symlink survival across plugin cache copy** — does a symlink inside the plugin directory survive the install/copy into `~/.claude/plugins/cache/.../`?

## Scope decisions (locked in during brainstorming)

| Decision | Choice |
|---|---|
| Execution shape | **Hybrid** — written procedure is the durable artifact; first pass runs live with maintainer driving a second terminal, assistant reading output in this session |
| Sandbox location | **Throwaway `/tmp/engram-plugin-test-YYYYMMDD`** — fresh dir, `.engram/events.db` is disposable, teardown is `rm -rf` |
| Test scope | **Baseline smokes + four unknowns** — six pre-checks gate the unknowns so we can triage failures cleanly |
| Fix policy | **Fix-on-blocker, defer-on-polish** — U1 is a correctness blocker and fixed in session; U2/U3/U4 findings are recorded and deferred to later phases |

## Sandbox setup

```sh
DATE=$(date +%Y%m%d)
mkdir /tmp/engram-plugin-test-$DATE
cd /tmp/engram-plugin-test-$DATE
git init -q
touch README.md
git add . && git commit -qm init
```

Launch Claude Code in the sandbox:

```sh
source /home/cdm/engram/.venv/bin/activate   # puts engram + engram-mcp on PATH
claude --plugin-dir /home/cdm/engram/plugin
```

**PATH note:** `engram` and `engram-mcp` are installed editable into `/home/cdm/engram/.venv/bin`. The shell that launches Claude Code must have that directory on `PATH` (either by activating the venv or exporting it explicitly). If `which engram` from the sandbox shell returns nothing, the hooks and MCP server will silently fail and every test below will appear broken.

**Teardown:** `rm -rf /tmp/engram-plugin-test-$DATE`. Findings live in the real Engram DB (see "Recording" below), not in the sandbox.

## Test matrix

Each test has a **probe**, **pass criterion**, and **fail action** (FIX = address in this session before moving on; DEFER = record and continue).

### Baseline smokes

The baseline smokes gate the unknowns. A failure here usually means "the plugin didn't install or wire up correctly" and must be diagnosed before interpreting unknown-test results.

#### S1 — Plugin loads

**Probe:** After launching Claude Code with `--plugin-dir`, check for plugin errors at startup. Run `/plugin list` and confirm `engram` is listed as loaded.

**Pass:** Plugin listed, no errors.

**Fail action:** **FIX**. Almost certainly a `plugin.json` schema issue. Blocker for everything downstream.

#### S2 — Skill discovered

**Probe:** Type `/` in the Claude Code prompt; `/engram:briefing` should appear in completion. Run `/engram:briefing`. Output should be a project briefing (note: the sandbox `.engram/events.db` is empty, so the briefing will be sparse — a minimal header is still a pass).

**Pass:** Skill discoverable and runs without error.

**Fail action:** **FIX**. Skill discovery is broken, or `allowed-tools: Bash(engram *)` syntax didn't parse. Blocker.

#### S3 — MCP connects

**Probe:** Run `/mcp` (or equivalent MCP status command) and confirm `engram` is listed as connected, not failed.

**Pass:** Connected.

**Fail action:** **FIX**. Most likely causes: `engram-mcp` not on PATH, or the env var issue that U1 is about to investigate — which means S3 and U1 may resolve together.

#### S4 — SessionStart hook fires

**Probe:** After launch (and after confirming S3), from a separate shell in the sandbox:
```sh
sqlite3 .engram/events.db 'SELECT id, agent_id, focus, started_at FROM sessions ORDER BY started_at DESC LIMIT 5;'
```
Expect a new row in the `sessions` table with `agent_id=claude-code`, `ended_at` NULL, and `started_at` matching the launch time. (SessionStart writes to the `sessions` table, not `events`.)

**Pass:** Active session row exists.

**Fail action:** **FIX**. Either the SessionStart hook didn't fire, or the hook command didn't resolve `engram`. Check `claude --debug` output.

#### S5 — PostToolUse (Edit) fires

**Probe:** Ask Claude Code to edit `README.md` (e.g., "add a line to README.md saying 'hello'"). After completion, re-query events:
```sh
sqlite3 .engram/events.db "SELECT event_type, agent_id, content FROM events WHERE event_type='mutation' ORDER BY timestamp DESC LIMIT 3;"
```
Expect a `mutation` event summarizing the edit, with `agent_id=claude-code`.

**Pass:** Mutation event recorded.

**Fail action:** Investigate. Matcher may be wrong, or hook command timed out. Likely FIX, depending on cause.

#### S6 — PostToolUse (Bash) fires

**Probe:** Ask Claude Code to run `ls` via Bash. Re-query:
```sh
sqlite3 .engram/events.db "SELECT event_type, agent_id, content FROM events WHERE event_type='outcome' ORDER BY timestamp DESC LIMIT 3;"
```
Expect an `outcome` event with `agent_id=claude-code`.

**Pass:** Outcome event recorded.

**Fail action:** Same treatment as S5.

### Unknowns

#### U1 — `${PWD}` expansion / project dir resolution

The plugin's `.mcp.json` currently sets `ENGRAM_PROJECT_DIR=${PWD}`. Docs show `${CLAUDE_PROJECT_DIR}` in hook examples but do not confirm any variable expansion in MCP env vars. Three possible outcomes:

**U1-A: `${PWD}` expands correctly.** Events land in the sandbox `.engram/events.db`. Current `.mcp.json` is fine. **No change.**

**U1-B: `${PWD}` does not expand, but `engram-mcp` is spawned in the user's CWD.** `engram-mcp` defaults to `os.getcwd()` when the env var is unset (confirmed in `src/engram/mcp_server.py:30` and other lines). **Fix: drop the `env` block entirely from `.mcp.json`.** Simpler than today.

**U1-C: `${PWD}` does not expand AND `engram-mcp` is spawned from the plugin cache directory.** Need a replacement. Try in order:
  1. `${CLAUDE_PROJECT_DIR}` as the env value.
  2. If that also doesn't work, ship a shell wrapper at `plugin/bin/engram-mcp-wrapper` (bash script that captures `$PWD` and execs `engram-mcp`). Update `.mcp.json` to use `${CLAUDE_PLUGIN_ROOT}/bin/engram-mcp-wrapper`.

**Probes (run both to disambiguate):**
- Where did events.db land? `ls -la /tmp/engram-plugin-test-$DATE/.engram/` — if missing, check `~/` or the plugin cache for a stray `.engram/` dir.
- Where was `engram-mcp` spawned? `ps auxf | grep engram-mcp` → note the PID → `readlink /proc/<pid>/cwd`.

**Fail action:** **FIX**. Try U1-B's drop-the-env-block approach first (simplest); if that doesn't work, fall through to U1-C's variants. Re-run S3+S4+S5 after each change until green.

#### U2 — Hook dedup with CLI-installed hooks

**Probe:**
1. Exit Claude Code.
2. In the sandbox, run `engram hooks install` (this writes `.claude/settings.json` with the same PostToolUse commands the plugin registers).
3. Relaunch with `--plugin-dir /home/cdm/engram/plugin`.
4. Ask Claude to make exactly one edit to README.md.
5. Count PostToolUse mutation events from that single edit (capture a baseline first, then diff):
```sh
# Before the edit:
sqlite3 .engram/events.db "SELECT COUNT(*) FROM events WHERE event_type='mutation';"
# After the edit:
sqlite3 .engram/events.db "SELECT COUNT(*) FROM events WHERE event_type='mutation';"
```
The diff between the two counts tells us how many hook invocations fired per edit.

**Pass (dedup):** count diff is 1. Claude Code merges identical hooks.

**Fail (double-fire):** count diff is 2. Both sources fire independently.

**Action:** **DEFER**. Record whichever outcome. If double-fire: the v1.7.0 release notes must warn users to uninstall CLI hooks first (`engram hooks uninstall`), and Phase 4 should teach the CLI installer to detect plugin presence. If dedup: the zero-friction migration path we assumed is real.

#### U3 — Skill can pre-approve an MCP tool

Currently, `plugin/skills/briefing/SKILL.md` uses `allowed-tools: Bash(engram briefing*)` and shells out via `!` execution. We want to know whether a skill can directly pre-approve an MCP tool (avoiding shell-out overhead and keeping things "more native").

**Probe:**
1. In `/home/cdm/engram/plugin/skills/`, create a throwaway skill `test-mcp/SKILL.md`:
   ```markdown
   ---
   name: test-mcp
   description: Test whether a skill can pre-approve an MCP tool call without a permission prompt.
   allowed-tools: mcp__engram__status
   ---

   Run the Engram MCP status tool and show the result.
   ```
2. In the live sandbox session, run `/reload-plugins` (or exit + relaunch).
3. Invoke `/engram:test-mcp`.
4. Observe: does Claude call `mcp__engram__status` without a permission prompt? Does the skill load without frontmatter error?

**Pass:** Skill loads; MCP tool runs without prompt.

**Fail modes:** (a) frontmatter parse error at load; (b) skill loads but prompts for permission on the MCP tool.

**Action:** **DEFER**. Current briefing skill uses Bash shell-out, which is unaffected by this result. Record the outcome. Remove `plugin/skills/test-mcp/` at end of session regardless of result.

#### U4 — Symlink survival in plugin cache

Docs claim symlinks are preserved across the plugin install (which copies the plugin directory into `~/.claude/plugins/cache/{id}/{version}/`). Untested for our case.

**Probe:**
1. Create a symlink inside the plugin: `ln -s ../README.md /home/cdm/engram/plugin/testlink`.
2. Commit nothing — we'll remove it after.
3. In the sandbox session, run `/reload-plugins` (or exit + relaunch with `--plugin-dir`).
4. Check the installed copy:
```sh
find ~/.claude/plugins/cache -name testlink -exec ls -la {} \;
```
(The cache path layout is `~/.claude/plugins/cache/{id}/{version}/` but the exact layout isn't worth memorizing — `find` is more robust.)

**Outcomes:**
- Still a symlink → preserved (pass).
- Regular file with content of target → copied-through (acceptable for many uses but breaks dynamic targets).
- Missing → not preserved.

**Action:** **DEFER**. We don't currently use symlinks in the plugin. Record the finding for future reference. Remove the test symlink (`rm /home/cdm/engram/plugin/testlink`) before finishing.

## Recording findings

Every test result flows back into the real Engram DB (not the sandbox DB — the real one at `/home/cdm/engram/.engram/events.db`).

### Resolving existing HIGH warnings

Four HIGH warnings are already recorded (Engram event dated 2026-04-21 22:15, scope `plugin/`, agent `claude-code`). Once each unknown is tested, **resolve the corresponding warning**, whether the behavior matched our assumption or not. The resolution note is the observed fact. Don't leave warnings open just because we "tested" them.

### Posting discoveries

For each confirmed behavior, post a new discovery:

- `type`: `discovery`
- `priority`: `high`
- `scope`: `plugin/`
- Body: one paragraph stating the verified fact (e.g., "Plugin MCP `.mcp.json` env var `${PWD}` does/doesn't expand as of Claude Code version X — observed 2026-04-23 in sandbox")

These become the durable record for future maintainers and for the next time we revise the plugin.

### Posting decisions

For any plugin code change triggered by U1's outcome, post a decision:

- `type`: `decision`
- `priority`: `high`
- `scope`: `plugin/.mcp.json` (or whichever files changed)
- Body: what we picked and why (e.g., "Dropped `env` block from `.mcp.json` because `${PWD}` didn't expand and `engram-mcp` defaults to `os.getcwd()`")

### Updating ROADMAP.md

`docs/ROADMAP.md#17` lists Phase 2b as an open item with four open design items. After Phase 2b completes:
- Mark Phase 2b as done, referencing the session date.
- For each of the four items, update the description with the observed behavior and link to the Engram event (or quote the key finding inline).

## Completion gate

Phase 2b is complete when ALL of the following hold:

- [ ] All six baseline smokes (S1–S6) pass.
- [ ] U1 is resolved: either U1-A (no change needed) or U1-B/C (fix applied and re-tested — S3, S4, S5 still pass after the fix).
- [ ] U2, U3, U4 findings are recorded as Engram discoveries (or warnings if a divergence was serious enough to warrant one).
- [ ] All four HIGH "UNVERIFIED" warnings from 2026-04-21 are resolved.
- [ ] `docs/ROADMAP.md#17` is updated to reflect Phase 2b outcomes.
- [ ] Sandbox `/tmp/engram-plugin-test-$DATE` is torn down.
- [ ] Throwaway test skill `plugin/skills/test-mcp/` and test symlink `plugin/testlink` are removed.

When all gates pass, Phase 3 (remaining MVP skills: `post-decision`, `query`, `checkpoint-save`, `checkpoint-restore`) can proceed on the same branch.

## Out of scope

- Writing the remaining MVP skills (Phase 3).
- Adding `ENGRAM_CONTEXT_DIRS` configuration (Phase 4).
- Subscribing to new hook events like PreCompact/PostCompact (deferred beyond v1.7).
- Marketplace submission (deferred per the 2026-04-21 decision).
- Any per-subagent event capture work (deferred beyond v1.7).
