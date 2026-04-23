# Phase 2b — Plugin Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the four-unknown plugin verification procedure in a live sandbox, record findings back into Engram, and leave the `v1.7-plugin` branch in a green state ready for Phase 3.

**Architecture:** Hybrid execution. The plan is a runbook the maintainer walks through in a second terminal (`claude --plugin-dir /home/cdm/engram/plugin`); the assistant in the driving session interprets outputs, decides branching, records findings via Engram MCP, and applies fixes to `plugin/.mcp.json` (U1 only). This is not a TDD feature build — the "tests" are live observational probes and the "implementation" is the recorded findings plus any U1 fix.

**Tech Stack:** bash, Python 3.12+ (for U1-E pre-test), sqlite3 CLI, Claude Code CLI (`--plugin-dir` dev mode), Engram MCP (`mcp__engram__*` tools from the driving session).

**Spec:** `docs/superpowers/specs/2026-04-23-phase-2b-plugin-verification-design.md` (commit `1b531a7`).

---

## File Structure

The plan touches a small, well-bounded set of files. Most changes are temporary (reverted at cleanup); only `.mcp.json` may persist, and only if U1-B/C/D is the outcome.

**Permanent (plan artifacts, committed):**
- Modify: `/home/cdm/engram/plugin/.mcp.json` — only if U1 outcome ≠ A
- Modify (conditional): `/home/cdm/engram/plugin/bin/engram-mcp-wrapper` — only if U1-C fallback 2 is needed (create new file + `chmod +x`)
- Modify: `/home/cdm/engram/docs/ROADMAP.md` — strike Phase 2b, record outcomes under item #17

**Temporary (created and torn down during the session):**
- Create + rm: `/home/cdm/engram/plugin/skills/test-mcp/SKILL.md` — U3 probe
- Create + rm: `/home/cdm/engram/plugin/testlink` — U4 probe
- Edit + revert: `/home/cdm/engram/plugin/hooks/hooks.json` — U2 probe (wrap then revert)
- Create + rm: `/tmp/engram-plugin-test-$DATE/` (sandbox dir, including `.engram/` and `.claude/`)
- Create + rm: `/tmp/hooktrace-plugin`, `/tmp/hooktrace-cli`, `/tmp/claude-stderr.log`, `/tmp/engram-u1e-decoy`

**Recorded in Engram (not in files):**
- Resolutions for the four HIGH warnings from 2026-04-21 22:15
- Discovery events for each observed behavior, stamped with Claude Code version
- A decision event if U1 resulted in a `.mcp.json` change

---

## Notation

Observations are recorded as you go. Two recording destinations:

- **Scratchpad** (for this session's memory): `/tmp/engram-plugin-test-$DATE/findings.md` — plain markdown, append-only. Lets us resume if the session is interrupted and consolidate into Engram at the end.
- **Engram** (the durable record): via `mcp__engram__post_event` and related tools. Only posted after the scratchpad entry is filled in, so the final task can batch-commit without copy-paste errors.

Tasks that record a finding will say: "Append to scratchpad: `...`" — literal text to append.

---

## Task 1: Pre-session hygiene

**Files:**
- Read only: `/home/cdm/engram/` (working copy, git status check)
- Read only: `/home/cdm/engram/.engram/events.db` (baseline count)

- [ ] **Step 1.1: Confirm clean working tree on the v1.7-plugin branch**

Run:
```sh
cd /home/cdm/engram && git status && git branch --show-current
```

Expected:
```
On branch v1.7-plugin
Your branch is up to date with 'origin/v1.7-plugin'.

nothing to commit, working tree clean
v1.7-plugin
```

If not on `v1.7-plugin` or working tree is dirty, stop and sort that out before starting. A mid-session probe will modify `plugin/hooks/hooks.json` and we need to be able to `git checkout -- plugin/hooks/hooks.json` to revert cleanly.

- [ ] **Step 1.2: Record baseline Engram event counts (to detect contamination later)**

Run:
```sh
sqlite3 /home/cdm/engram/.engram/events.db \
  "SELECT event_type, COUNT(*) FROM events GROUP BY event_type ORDER BY event_type;"
sqlite3 /home/cdm/engram/.engram/events.db \
  "SELECT COUNT(*) FROM sessions;"
```

Record the two tables in a scratchpad (you'll re-run these at the end to confirm only intentional events were added).

- [ ] **Step 1.3: Confirm the four HIGH warnings are still open in Engram**

Use the `mcp__engram__query` tool (from the driving session) to find the warnings:
```
query: 'UNVERIFIED plugin'
type: warning
status: active
```

Expected: 4 active HIGH warnings dated 2026-04-21, scope `plugin/`, all flagged UNVERIFIED — one for each of U1/U2/U3/U4. Note their event IDs; you'll resolve them in Task 16.

- [ ] **Step 1.4: Capture the Claude Code version**

Run:
```sh
claude --version
```

Expected: a version string like `claude vX.Y.Z`. **Record this in the scratchpad** — every Engram discovery posted in Task 16 will cite this version.

---

## Task 2: Sandbox setup

**Files:**
- Create: `/tmp/engram-plugin-test-$DATE/` (new sandbox)
- Create: `/tmp/engram-plugin-test-$DATE/README.md` (target for Edit probes)
- Create: `/tmp/engram-plugin-test-$DATE/findings.md` (scratchpad)

- [ ] **Step 2.1: Create the sandbox**

Run:
```sh
DATE=$(date +%Y%m%d)
mkdir /tmp/engram-plugin-test-$DATE
cd /tmp/engram-plugin-test-$DATE
touch README.md
echo "# Phase 2b findings scratchpad ($DATE)" > findings.md
echo "Claude Code version: <fill in from Task 1.4>" >> findings.md
```

Expected: no errors. `ls -la` shows `README.md` and `findings.md`.

- [ ] **Step 2.2: Pre-flight check for stale U4 symlink artifact**

Run:
```sh
test -e /home/cdm/engram/plugin/testlink && \
  echo "ERROR: stale testlink at plugin/testlink — remove and restart" && exit 1
echo "pre-flight clean"
```

Expected: `pre-flight clean`. If it prints ERROR, `rm /home/cdm/engram/plugin/testlink` and re-run.

- [ ] **Step 2.3: Install crash-safety trap in the launch shell**

Run (in the same shell that will launch `claude`):
```sh
trap 'rm -f /home/cdm/engram/plugin/testlink /tmp/hooktrace-plugin /tmp/hooktrace-cli' EXIT
```

No output on success. The trap clears U2 and U4 artifacts if the session aborts.

- [ ] **Step 2.4: Activate the venv so engram / engram-mcp are on PATH**

Run:
```sh
source /home/cdm/engram/.venv/bin/activate
which engram engram-mcp
```

Expected: both print paths under `/home/cdm/engram/.venv/bin/`. If either is missing, run `pip install -e "/home/cdm/engram[all]"` from that venv and retry.

---

## Task 3: U1-E pre-test — confirm engram-mcp honors ENGRAM_PROJECT_DIR

**Files:** None modified. This creates and removes `/tmp/engram-u1e-decoy/`.

- [ ] **Step 3.1: Run the decoy env var test**

Run:
```sh
rm -rf /tmp/engram-u1e-decoy
ENGRAM_PROJECT_DIR=/tmp/engram-u1e-decoy /home/cdm/engram/.venv/bin/python -c "
import os
from pathlib import Path
from engram.store import EventStore
pd = Path(os.environ.get('ENGRAM_PROJECT_DIR', os.getcwd()))
pd.mkdir(parents=True, exist_ok=True)
db = pd / '.engram' / 'events.db'
db.parent.mkdir(exist_ok=True)
store = EventStore(db)
_ = store.conn
store.close()
print('project_dir:', pd)
print('db exists:', db.exists())
"
```

Expected output:
```
project_dir: /tmp/engram-u1e-decoy
db exists: True
```

- [ ] **Step 3.2: Confirm the DB file landed in the decoy dir**

Run:
```sh
ls -la /tmp/engram-u1e-decoy/.engram/
```

Expected: `events.db` present in that directory.

- [ ] **Step 3.3: Clean up the decoy**

Run:
```sh
rm -rf /tmp/engram-u1e-decoy
```

- [ ] **Step 3.4: Record outcome**

Append to `/tmp/engram-plugin-test-$DATE/findings.md`:
```
## U1-E pre-test
engram-mcp/EventStore honors ENGRAM_PROJECT_DIR: [PASS / FAIL]
<paste the two expected-output lines>
```

If FAIL, stop Phase 2b and fix `src/engram/mcp_server.py` first — the env var must be honored before U1's A/B/C/D branches become distinguishable.

---

## Task 4: Launch Claude Code and run S1

**Files:** None modified. Creates `/tmp/claude-stderr.log`.

- [ ] **Step 4.1: Launch Claude Code in the sandbox**

Run:
```sh
cd /tmp/engram-plugin-test-$DATE
claude --debug --plugin-dir /home/cdm/engram/plugin 2>/tmp/claude-stderr.log
```

Claude Code opens. Leave it running — subsequent probes run inside it or in separate shells.

- [ ] **Step 4.2: S1 — check stderr for load errors**

From a second shell (not the one running Claude):
```sh
grep -iE 'error|failed' /tmp/claude-stderr.log | head -20
```

Expected: nothing plugin-related. Generic `claude --debug` warnings are fine; any line mentioning `engram`, `plugin load`, or a plugin-manifest schema error is a fail.

- [ ] **Step 4.3: S1 — confirm engram is registered**

Inside Claude Code, run:
```
/plugin list
```

Expected: `engram` appears in the list with no "failed" or "error" annotation.

- [ ] **Step 4.4: S1 — check Errors tab (if the UI exposes one)**

Inside Claude Code, run `/plugin` and navigate to the Errors tab if it exists. Must be empty for engram.

- [ ] **Step 4.5: Record S1 outcome**

Append to `findings.md`:
```
## S1 — Plugin loads
stderr clean: [yes/no, paste any engram-related lines]
/plugin list shows engram: [yes/no, paste the line]
Errors tab empty: [yes/no/no-such-tab]
S1: [PASS / FAIL]
```

If FAIL, the plugin manifest is broken — stop and fix `plugin/.claude-plugin/plugin.json` before proceeding. This is a blocker.

---

## Task 5: S2 — Skill discovered

**Files:** None modified.

- [ ] **Step 5.1: Verify the slash command appears**

Inside Claude Code, type `/` (do not press enter). Look for `/engram:briefing` in the completion menu.

- [ ] **Step 5.2: Run the briefing skill**

Inside Claude Code, invoke:
```
/engram:briefing
```

Expected: output is a project briefing. Since the sandbox `.engram/events.db` is empty at this point (or being created right now), the briefing will be minimal — a header + "no events" kind of output. That's a pass; we're testing discoverability and invocation, not content.

- [ ] **Step 5.3: Record S2 outcome**

Append to `findings.md`:
```
## S2 — Skill discovered
/engram:briefing appears in completion: [yes/no]
Skill invocation runs without error: [yes/no]
S2: [PASS / FAIL]
```

If FAIL, skill discovery is broken or `allowed-tools: Bash(engram briefing*)` frontmatter didn't parse. Blocker.

---

## Task 6: S3 — MCP connects and resolves the right project dir (combined with U1 diagnosis)

**Files:** None modified yet. Records the three probes that disambiguate U1 outcomes.

- [ ] **Step 6.1: Confirm MCP is connected**

Inside Claude Code, run `/mcp` and locate `engram` in the list.

Append to `findings.md`:
```
## S3 — MCP + project_dir diagnosis
engram MCP status: [connected / failed / missing]
```

If not connected, jump straight to Step 6.2 and 6.3 to see why — the usual cause is a project_dir misresolution (i.e., this is U1 showing up).

- [ ] **Step 6.2: Find the spawned cwd of the engram-mcp process**

From a second shell:
```sh
ps auxf | grep -i engram-mcp | grep -v grep
```

Note the PID of the `engram-mcp` process (there should be exactly one). Then:
```sh
readlink /proc/<PID>/cwd
```

Expected (U1-A): `/tmp/engram-plugin-test-$DATE` (the sandbox).

Append to `findings.md`:
```
engram-mcp PID: <pid>
engram-mcp spawned cwd: <path>
Expected (U1-A): /tmp/engram-plugin-test-$DATE
```

- [ ] **Step 6.3: Ask the MCP server what project_dir it thinks it's on**

Inside Claude Code, invoke the `mcp__engram__status` MCP tool. The response includes the DB path.

Append to `findings.md`:
```
mcp__engram__status reported db path: <path>
Expected (U1-A): /tmp/engram-plugin-test-$DATE/.engram/events.db
```

- [ ] **Step 6.4: Scan for .engram/ dirs created by this launch**

From a second shell:
```sh
find /tmp/engram-plugin-test-$DATE ~/.claude/plugins/cache ~/.engram /home/cdm/engram \
  -type d -name .engram -newer /tmp/engram-plugin-test-$DATE 2>/dev/null
```

Expected (U1-A): exactly one match at `/tmp/engram-plugin-test-$DATE/.engram`. Zero matches means the server hasn't connected / written anything yet. More than one match means a stray `.engram/` was created elsewhere (almost certainly a U1-C or U1-D failure).

Append to `findings.md`:
```
.engram/ dir scan results:
<paste find output>
```

- [ ] **Step 6.5: Classify as U1-A/B/C/D**

Read the three outputs above and select one branch per the spec (see `docs/superpowers/specs/2026-04-23-phase-2b-plugin-verification-design.md` §U1):

- **U1-A** (all three clean, everything in sandbox): record PASS, proceed to Task 8.
- **U1-B** (cwd is sandbox, but project_dir reads literal `${PWD}` or the env var passed through unexpanded): proceed to Task 7 branch B.
- **U1-C** (cwd is plugin cache, project_dir wrong): proceed to Task 7 branch C.
- **U1-D** (cwd is sandbox but project_dir is a different *real* path — e.g., $HOME or the launch dir): proceed to Task 7 branch D.

Append to `findings.md`:
```
S3: [PASS / FAIL]
U1 outcome classification: [A / B / C / D]
```

If U1-A, skip Task 7 and go directly to Task 8.

---

## Task 7: U1 fix (conditional — only if U1 classification is B, C, or D)

**Files:**
- Modify: `/home/cdm/engram/plugin/.mcp.json`
- Conditionally create: `/home/cdm/engram/plugin/bin/engram-mcp-wrapper` (U1-C fallback 2 only)

- [ ] **Step 7.1 (branch B only): Drop the env block from .mcp.json**

Current `.mcp.json`:
```json
{
  "mcpServers": {
    "engram": {
      "command": "engram-mcp",
      "env": {
        "ENGRAM_PROJECT_DIR": "${PWD}"
      }
    }
  }
}
```

Replace with:
```json
{
  "mcpServers": {
    "engram": {
      "command": "engram-mcp"
    }
  }
}
```

`engram-mcp` will fall back to `os.getcwd()`, which — per U1-B diagnosis — is the sandbox dir.

- [ ] **Step 7.2 (branch C or D first attempt): Switch to ${CLAUDE_PROJECT_DIR}**

Edit `.mcp.json`:
```json
{
  "mcpServers": {
    "engram": {
      "command": "engram-mcp",
      "env": {
        "ENGRAM_PROJECT_DIR": "${CLAUDE_PROJECT_DIR}"
      }
    }
  }
}
```

- [ ] **Step 7.3 (branch C fallback 2 only — if Step 7.2 also fails): Ship a wrapper script**

Create `/home/cdm/engram/plugin/bin/engram-mcp-wrapper`:
```sh
#!/bin/sh
# Captures $CLAUDE_PROJECT_DIR (set by Claude Code for hooks) or falls back
# to the current working directory, then execs engram-mcp.
export ENGRAM_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
exec engram-mcp "$@"
```

Then:
```sh
chmod +x /home/cdm/engram/plugin/bin/engram-mcp-wrapper
```

Update `.mcp.json`:
```json
{
  "mcpServers": {
    "engram": {
      "command": "${CLAUDE_PLUGIN_ROOT}/bin/engram-mcp-wrapper"
    }
  }
}
```

- [ ] **Step 7.4: Exit Claude Code and relaunch**

Inside Claude Code: `/quit` (or `exit`). From the launch shell:
```sh
cd /tmp/engram-plugin-test-$DATE
claude --debug --plugin-dir /home/cdm/engram/plugin 2>>/tmp/claude-stderr.log
```

Note the `>>` (append) — previous stderr kept for reference.

- [ ] **Step 7.5: Re-run the full S1–S3 diagnosis**

Execute Task 4 Steps 4.2–4.5 and Task 6 Steps 6.1–6.4 again. All three S3 axes (connected, cwd, project_dir) must now point to the sandbox. Append re-test results to `findings.md` under a new heading:
```
## Task 7 re-test after U1 fix (attempt N)
<S1 results>
<S3 results>
```

- [ ] **Step 7.6: Decide next step**

- If S3 is now green: proceed to Task 8. Append `U1 fix: <B | C-via-CLAUDE_PROJECT_DIR | C-via-wrapper | D>` to findings.
- If S3 still fails: escalate within the same branch (B → C; C fallback 1 → C fallback 2). Append the new attempt to findings and loop back to 7.4.
- If all fallbacks exhausted: stop Phase 2b. Append a detailed failure note and a TODO for a design consultation.

- [ ] **Step 7.7: Commit the U1 fix (only if one was applied and verified)**

Run:
```sh
cd /home/cdm/engram
git add plugin/.mcp.json plugin/bin/engram-mcp-wrapper 2>/dev/null
git status
git commit -m "fix: plugin .mcp.json project_dir resolution

Phase 2b verification found that <summary of the specific failure>.
Fix: <which branch — B, C variant 1, C variant 2, or D — and why>.
Verified via S1-S3 re-run with Claude Code <version from Task 1.4>."
```

(The `2>/dev/null` on `git add` is because `plugin/bin/engram-mcp-wrapper` may not exist in branches B or C-variant-1.)

---

## Task 8: S4 — SessionStart hook fires

**Files:** None modified. Reads `/tmp/engram-plugin-test-$DATE/.engram/events.db`.

- [ ] **Step 8.1: Query the sessions table**

From a second shell:
```sh
sqlite3 /tmp/engram-plugin-test-$DATE/.engram/events.db \
  'SELECT id, agent_id, focus, started_at, ended_at FROM sessions ORDER BY started_at DESC LIMIT 5;'
```

Expected: at least one row with `agent_id=claude-code`, `ended_at` NULL or a recent timestamp, and `started_at` matching when Claude Code launched in this session (within the last few minutes).

- [ ] **Step 8.2: Record S4 outcome**

Append to `findings.md`:
```
## S4 — SessionStart hook fires
Active sessions row count: <n>
Most recent row: <paste>
S4: [PASS / FAIL]
```

If FAIL (no row at all): the SessionStart hook didn't fire. Check `claude --debug` output (`grep -i 'session-start\|SessionStart' /tmp/claude-stderr.log`). Most likely the `engram` CLI isn't resolvable — re-verify Task 2 Step 2.4.

---

## Task 9: S5 — PostToolUse Edit hook fires

**Files:** Touches `/tmp/engram-plugin-test-$DATE/README.md`.

- [ ] **Step 9.1: Ask Claude to edit README.md**

Inside Claude Code prompt:
```
Add a line to README.md that says "hello from S5".
```

Claude should use the Edit (or Write) tool. Wait for completion.

- [ ] **Step 9.2: Verify the mutation event was recorded**

From a second shell:
```sh
sqlite3 /tmp/engram-plugin-test-$DATE/.engram/events.db \
  "SELECT event_type, agent_id, scope, substr(content,1,100) FROM events \
   WHERE event_type='mutation' ORDER BY timestamp DESC LIMIT 3;"
```

Expected: at least one row with `event_type=mutation`, `agent_id=claude-code`, `scope` referencing README.md, `content` mentioning the edit.

- [ ] **Step 9.3: Record S5 outcome**

Append to `findings.md`:
```
## S5 — PostToolUse (Edit) fires
Mutation event present: [yes/no]
Row content: <paste>
S5: [PASS / FAIL]
```

---

## Task 10: S6 — PostToolUse Bash hook fires

**Files:** None.

- [ ] **Step 10.1: Ask Claude to run a Bash command**

Inside Claude Code:
```
Run `ls` to show the files here.
```

Claude uses the Bash tool. Wait for completion.

- [ ] **Step 10.2: Verify the outcome event was recorded**

From a second shell:
```sh
sqlite3 /tmp/engram-plugin-test-$DATE/.engram/events.db \
  "SELECT event_type, agent_id, scope, substr(content,1,100) FROM events \
   WHERE event_type='outcome' ORDER BY timestamp DESC LIMIT 3;"
```

Expected: a row with `event_type=outcome`, `agent_id=claude-code`, `content` mentioning `ls`.

- [ ] **Step 10.3: Record S6 outcome**

Append to `findings.md`:
```
## S6 — PostToolUse (Bash) fires
Outcome event present: [yes/no]
Row content: <paste>
S6: [PASS / FAIL]
```

At this point the baseline smokes are complete. If any of S1–S6 is FAIL and wasn't resolved in Task 7, stop and address before moving to the unknowns.

---

## Task 11: U2 setup — instrument both hook sources

**Files:**
- Modify (temp): `/home/cdm/engram/plugin/hooks/hooks.json`
- Modify (temp): `/tmp/engram-plugin-test-$DATE/.claude/settings.json`
- Create: `/tmp/hooktrace-plugin`, `/tmp/hooktrace-cli` (empty)

- [ ] **Step 11.1: Exit Claude Code**

Inside Claude Code: `/quit`.

- [ ] **Step 11.2: Truncate the trace files**

Run:
```sh
: > /tmp/hooktrace-plugin
: > /tmp/hooktrace-cli
```

Both files now exist and are empty.

- [ ] **Step 11.3: Wrap the plugin PostToolUse Edit hook with a trace signature**

Current `plugin/hooks/hooks.json` (the relevant section):
```json
{
  "matcher": "Write|Edit",
  "hooks": [
    {
      "type": "command",
      "command": "engram hook post-tool-use",
      "timeout": 10
    }
  ]
}
```

Replace the `command` value so it becomes:
```json
"command": "sh -c 'echo plugin >> /tmp/hooktrace-plugin; engram hook post-tool-use'"
```

Leave the `"matcher": "Bash"` block alone (we're only testing the Edit-matcher dedup; Bash would fire on all the setup commands and confuse the count).

- [ ] **Step 11.4: Install CLI hooks in the sandbox, then wrap them**

In the sandbox:
```sh
cd /tmp/engram-plugin-test-$DATE
engram hooks install
```

This writes `/tmp/engram-plugin-test-$DATE/.claude/settings.json`. Open it and edit the PostToolUse `Write|Edit` block's `command` field from `engram hook post-tool-use` to:
```json
"command": "sh -c 'echo cli >> /tmp/hooktrace-cli; engram hook post-tool-use'"
```

- [ ] **Step 11.5: Relaunch Claude Code with both sources active**

```sh
cd /tmp/engram-plugin-test-$DATE
claude --debug --plugin-dir /home/cdm/engram/plugin 2>>/tmp/claude-stderr.log
```

---

## Task 12: U2 probe + cleanup

**Files:**
- Modify (revert): `/home/cdm/engram/plugin/hooks/hooks.json`
- Delete: `/tmp/engram-plugin-test-$DATE/.claude/settings.json` (via `engram hooks uninstall`)

- [ ] **Step 12.1: Ask Claude for exactly one edit**

Inside Claude Code:
```
Change the line "hello from S5" in README.md to "hello from U2".
```

Wait for completion. Do not ask for anything else in this session.

- [ ] **Step 12.2: Inspect the trace files**

From a second shell:
```sh
echo "plugin: $(wc -l < /tmp/hooktrace-plugin) lines"
echo "cli:    $(wc -l < /tmp/hooktrace-cli) lines"
cat /tmp/hooktrace-plugin
cat /tmp/hooktrace-cli
```

- [ ] **Step 12.3: Classify the outcome**

Map to the outcome table in the spec §U2:

| plugin | cli | Interpretation |
|---|---|---|
| 1 | 0 | plugin wins (dedup prefers plugin) |
| 0 | 1 | cli wins (dedup prefers user settings) |
| 1 | 1 | **double-fire** |
| 0 | 0 | neither fired (investigate — hook is broken) |
| N≥2 | * | Claude issued N tool_use blocks per edit; divide through |

Append to `findings.md`:
```
## U2 — Hook dedup
plugin trace lines: <n>
cli trace lines: <n>
Outcome: <plugin-wins / cli-wins / double-fire / neither / multi-block>
```

- [ ] **Step 12.4: Exit Claude Code**

Inside Claude Code: `/quit`.

- [ ] **Step 12.5: Revert plugin/hooks/hooks.json**

Run:
```sh
cd /home/cdm/engram
git diff plugin/hooks/hooks.json    # sanity check — confirm only the wrapper change is staged
git checkout -- plugin/hooks/hooks.json
git diff plugin/hooks/hooks.json    # should now be empty
```

- [ ] **Step 12.6: Uninstall CLI hooks from the sandbox**

```sh
cd /tmp/engram-plugin-test-$DATE
engram hooks uninstall
```

Confirm `.claude/settings.json` no longer has a `hooks` block (or the file is gone).

- [ ] **Step 12.7: Truncate trace files**

```sh
: > /tmp/hooktrace-plugin
: > /tmp/hooktrace-cli
```

---

## Task 13: U3 pass 1 — skill invokes MCP tool WITHOUT permissions.allow

**Files:**
- Create (temp): `/home/cdm/engram/plugin/skills/test-mcp/SKILL.md`

- [ ] **Step 13.1: Create the throwaway skill**

Create `/home/cdm/engram/plugin/skills/test-mcp/SKILL.md`:
```markdown
---
name: test-mcp
description: Test whether a skill can invoke an MCP tool.
allowed-tools: mcp__engram__status
---

Run the Engram MCP status tool and show the result.
```

- [ ] **Step 13.2: Confirm sandbox settings has no permissions.allow for the MCP tool**

```sh
test -f /tmp/engram-plugin-test-$DATE/.claude/settings.json && \
  grep -E 'permissions|engram__status' /tmp/engram-plugin-test-$DATE/.claude/settings.json || \
  echo "no sandbox settings.json — clean"
```

Expected: either the file doesn't exist yet (clean), or if it does, it has no `permissions.allow` entry mentioning `engram__status`. If there IS such an entry from a prior run, remove it before proceeding.

- [ ] **Step 13.3: Launch Claude Code fresh**

```sh
cd /tmp/engram-plugin-test-$DATE
claude --debug --plugin-dir /home/cdm/engram/plugin 2>>/tmp/claude-stderr.log
```

- [ ] **Step 13.4: Run the test skill and observe**

Inside Claude Code, type `/` and look for `/engram:test-mcp`. If present: (Q1 = pass), invoke it. Observe:

- Does Claude try to call `mcp__engram__status`? (Q2)
- Does a permission prompt appear before the call? (Q3 pass 1)

Append to `findings.md`:
```
## U3 pass 1 — no permissions.allow
Q1 (skill loads / appears in completion): [yes/no]
  Stderr error about test-mcp, if any: <paste>
Q2 (Claude attempts mcp__engram__status): [yes/no/n-a]
Q3 (permission prompt appears): [yes/no/n-a]
Q3 interpretation: allowed-tools alone [does / does not] suppress the prompt
```

---

## Task 14: U3 pass 2 — skill invokes MCP tool WITH permissions.allow

**Files:**
- Modify (temp): `/tmp/engram-plugin-test-$DATE/.claude/settings.json`

- [ ] **Step 14.1: Exit Claude Code**

Inside Claude Code: `/quit`.

- [ ] **Step 14.2: Add the MCP tool to permissions.allow**

In the sandbox, write or edit `/tmp/engram-plugin-test-$DATE/.claude/settings.json`:
```json
{
  "permissions": {
    "allow": [
      "mcp__engram__status"
    ]
  }
}
```

If the file already has other content, merge the `permissions.allow` entry in rather than overwriting.

- [ ] **Step 14.3: Relaunch Claude Code**

```sh
cd /tmp/engram-plugin-test-$DATE
claude --debug --plugin-dir /home/cdm/engram/plugin 2>>/tmp/claude-stderr.log
```

- [ ] **Step 14.4: Run the test skill again**

Inside Claude Code, invoke `/engram:test-mcp`. Observe:
- Does the prompt suppress this time? (Q3 pass 2)

Append to `findings.md`:
```
## U3 pass 2 — with permissions.allow
Q3 (permission prompt appears with permissions.allow): [yes/no]
Final Q3 interpretation:
  - If prompt suppressed here but not in pass 1 → permissions.allow is required
  - If prompt suppressed in both → allowed-tools alone is sufficient
  - If prompt still fires → unusable for native MCP invocation
```

- [ ] **Step 14.5: Cleanup — exit, remove test skill, remove permissions.allow entry**

Inside Claude Code: `/quit`. Then:
```sh
rm -rf /home/cdm/engram/plugin/skills/test-mcp/
# If sandbox settings.json had ONLY the test permissions.allow, delete it:
rm -f /tmp/engram-plugin-test-$DATE/.claude/settings.json
# (If it has other keys, manually strip the test permissions.allow entry instead.)
```

- [ ] **Step 14.6: Sanity-check plugin tree is clean**

```sh
cd /home/cdm/engram
git status plugin/
# Expected: clean (no changes), since test-mcp was in skills/ and is now removed
```

---

## Task 15: U4 — Symlink survival + cleanup

**Files:**
- Create (temp): `/home/cdm/engram/plugin/testlink` (symlink)

- [ ] **Step 15.1: Snapshot the plugin cache to see whether --plugin-dir even uses it**

```sh
find ~/.claude/plugins/cache -maxdepth 4 -name '*engram*' 2>/dev/null
```

If this returns empty, `--plugin-dir` dev mode runs the plugin in-place and nothing gets copied. In that case the symlink question is trivially "not applicable for dev mode" — record that outcome and skip Step 15.3 (the real-install fallback would be worth doing but is out of scope for Phase 2b; note in findings).

- [ ] **Step 15.2: Create the test symlink**

```sh
ln -s ../README.md /home/cdm/engram/plugin/testlink
ls -la /home/cdm/engram/plugin/testlink
```

Expected: a symlink pointing to `../README.md`.

- [ ] **Step 15.3: Relaunch Claude Code (only if Step 15.1 showed the cache IS populated)**

```sh
cd /tmp/engram-plugin-test-$DATE
claude --debug --plugin-dir /home/cdm/engram/plugin 2>>/tmp/claude-stderr.log
```

Inside Claude Code, wait until `/plugin list` shows engram. Then exit: `/quit`.

- [ ] **Step 15.4: Check if the symlink survived in cache**

```sh
find ~/.claude/plugins/cache -name testlink -exec ls -la {} \;
```

Append to `findings.md`:
```
## U4 — Symlink survival
Cache populated by --plugin-dir: [yes/no]
If yes:
  testlink in cache: [still-symlink / regular-file / missing]
  Full output: <paste>
If no:
  --plugin-dir dev mode skips the cache copy; symlink question is moot for dev mode.
  Real-install test deferred out of Phase 2b scope.
```

- [ ] **Step 15.5: Cleanup**

```sh
rm /home/cdm/engram/plugin/testlink
ls /home/cdm/engram/plugin/testlink 2>&1   # should say "No such file"
cd /home/cdm/engram
git status plugin/   # should be clean
```

---

## Task 16: Record findings in Engram

**Files:** None. Posts events via `mcp__engram__*` tools from the driving session.

The scratchpad at `/tmp/engram-plugin-test-$DATE/findings.md` now has one entry per probe. Copy the key facts into Engram.

- [ ] **Step 16.1: Resolve the four HIGH warnings from 2026-04-21 22:15**

There is no MCP tool for resolution; use the `engram resolve` CLI command. Run each from a shell inside `/home/cdm/engram` (NOT the sandbox — we're updating the real project DB):

```sh
cd /home/cdm/engram
engram resolve <U1_event_id> -r "Phase 2b verified: outcome U1-<A/B/C/D>. <one-line summary>. Claude Code <version>."
engram resolve <U2_event_id> -r "Phase 2b verified: hooks <dedup-plugin-wins / dedup-cli-wins / double-fire / neither>. Claude Code <version>."
engram resolve <U3_event_id> -r "Phase 2b verified: allowed-tools <loads/doesn't load> MCP tool names; prompt <suppressed by allowed-tools alone / requires permissions.allow / always fires>. Claude Code <version>."
engram resolve <U4_event_id> -r "Phase 2b verified: --plugin-dir dev mode <skips/populates> cache; symlink <preserved / copied-through / missing / n-a>. Claude Code <version>."
```

Each command prints `Resolved: <event_id>` and `Reason: ...` on success. If `engram resolve` reports `not active`, the event was already resolved — verify and move on.

- [ ] **Step 16.2: Post a discovery for each confirmed behavior**

Four discoveries (one per unknown). Use the `mcp__engram__post_event` MCP tool from the driving Claude Code session (which is rooted in `/home/cdm/engram` and will write to the real project DB).

Arguments for each call:
- `event_type`: `"discovery"`
- `priority`: `"high"`
- `scope`: `["plugin/"]` — note: this is a LIST of path strings, not a single string
- `agent_id`: leave as default (`"claude-code"`)
- `content`: one-paragraph statement of the verified fact, copied from the scratchpad, ENDING with: `— observed 2026-04-23 with Claude Code <version>`

Example for U1 (U1-A outcome):
```
Plugin MCP .mcp.json env var ${PWD} expands correctly to the user's working directory when Claude Code launches engram-mcp. The plugin as shipped in plugin/.mcp.json works without modification. — observed 2026-04-23 with Claude Code vX.Y.Z
```

Example for U2 (double-fire outcome):
```
When the plugin's hooks/hooks.json and the user's .claude/settings.json both register a PostToolUse Edit command, Claude Code fires BOTH hooks independently for one edit (trace files show 1 plugin line + 1 cli line). Plugin install must detect existing CLI hooks and error/skip; v1.7.0 release notes must warn users to run `engram hooks uninstall` first. — observed 2026-04-23 with Claude Code vX.Y.Z
```

Repeat for U3 and U4. Copy facts verbatim from the scratchpad — do not paraphrase.

- [ ] **Step 16.3: Post a decision if U1 resulted in an .mcp.json change**

Only if Task 7 applied a fix. Use `mcp__engram__post_event`:
- `event_type`: `"decision"`
- `priority`: `"high"`
- `scope`: `["plugin/.mcp.json"]` (add `"plugin/bin/engram-mcp-wrapper"` to the list too if the wrapper was created — scope is a list)
- `content`: one paragraph stating what was changed, why, and citing the S1–S6 re-run that verified it. Example:
  ```
  U1 fallback applied: dropped the `env` block from plugin/.mcp.json because Claude Code vX.Y.Z does not expand ${PWD} in MCP env vars, and engram-mcp correctly defaults to os.getcwd() (which was the user's sandbox dir). S1–S6 all green after the fix. Commit <hash>. — observed 2026-04-23
  ```

- [ ] **Step 16.4: Verify nothing escaped into the real Engram DB accidentally**

Re-run the baseline query from Task 1 Step 1.2:
```sh
sqlite3 /home/cdm/engram/.engram/events.db \
  "SELECT event_type, COUNT(*) FROM events GROUP BY event_type ORDER BY event_type;"
```

Compare with the Task 1 Step 1.2 baseline. The `discovery` count should be +4 and `decision` should be +0 or +1 (depending on U1). Session count should be +1 (this session). No other categories should have changed.

Append to `findings.md`:
```
## Engram DB delta check
Before: <paste Task 1 baseline>
After:  <paste current>
Delta matches expected (+4 discoveries, +0/1 decisions, +1 session): [yes/no]
```

If the delta doesn't match, investigate before closing the session.

---

## Task 17: Update ROADMAP.md

**Files:**
- Modify: `/home/cdm/engram/docs/ROADMAP.md`

- [ ] **Step 17.1: Locate the Phase 2b section**

Item #17 — "Claude Code Plugin Packaging" — contains the Phase 2b open item.

- [ ] **Step 17.2: Strike Phase 2b as done and fold findings in**

For each of the four "open design items" listed in #17, replace the description with the observed outcome. Example before:
```
- **${PWD} expansion in .mcp.json env vars** — UNVERIFIED. Test before committing.
```

Example after (U1-A):
```
- **${PWD} expansion in .mcp.json env vars** — VERIFIED 2026-04-23. ${PWD} expands to the user CWD in MCP env vars. Current .mcp.json is correct.
```

Example after (U1-B):
```
- **${PWD} expansion in .mcp.json env vars** — VERIFIED 2026-04-23. ${PWD} is NOT expanded in MCP env vars as of Claude Code <version>. Dropped the env block; engram-mcp falls back to os.getcwd(), which is the sandbox dir. Fix in commit <hash>.
```

Mark the Phase 2b bullet done:
```
- [x] Phase 2b — live sandbox verification of the four unknowns. Completed 2026-04-23. See docs/superpowers/specs/2026-04-23-phase-2b-plugin-verification-design.md and Engram discoveries scoped to `plugin/`.
```

- [ ] **Step 17.3: Commit ROADMAP changes**

```sh
cd /home/cdm/engram
git add docs/ROADMAP.md
git commit -m "docs: record Phase 2b outcomes in ROADMAP #17

Phase 2b completed 2026-04-23. Four unknowns resolved:
- U1: <outcome>
- U2: <outcome>
- U3: <outcome>
- U4: <outcome>

Findings also posted as discoveries in Engram (scope plugin/)."
```

---

## Task 18: Completion gate + teardown

**Files:** None modified; final verification only.

- [ ] **Step 18.1: Check every item of the completion gate from the spec**

Walk through `docs/superpowers/specs/2026-04-23-phase-2b-plugin-verification-design.md` §Completion gate. For each bullet, confirm it holds:

- [x] All six baseline smokes (S1–S6) pass **in the final state** — if U1 fix was applied in Task 7, use the Task 7 Step 7.5 re-run results.
- [x] U1 resolved with fix applied and verified.
- [x] U2, U3, U4 findings recorded as discoveries.
- [x] All four 2026-04-21 HIGH warnings are resolved (verify via `mcp__engram__query` type=warning status=resolved).
- [x] Every posted discovery includes the Claude Code version.
- [x] No stray `.engram/` directories outside the sandbox — verify with:
  ```sh
  find /home /tmp ~/.claude -maxdepth 6 -type d -name .engram 2>/dev/null
  ```
  Expected matches: `/home/cdm/engram/.engram` and `/tmp/engram-plugin-test-$DATE/.engram` only.
- [x] `docs/ROADMAP.md#17` updated (committed in Task 17).
- [x] `plugin/hooks/hooks.json` reverted (confirmed at Task 12 Step 12.5).
- [x] `plugin/skills/test-mcp/` removed (confirmed at Task 14 Step 14.5).
- [x] `plugin/testlink` removed (confirmed at Task 15 Step 15.5).
- [x] Trace files removed (`rm -f /tmp/hooktrace-plugin /tmp/hooktrace-cli`).

- [ ] **Step 18.2: Final git sanity check**

```sh
cd /home/cdm/engram
git status
git log --oneline v1.7-plugin..HEAD   # commits added this session
```

Expected: working tree clean. New commits: 0 (no fix) or 1 (U1 fix in Task 7) + 1 (ROADMAP in Task 17) = up to 2 commits added this session.

- [ ] **Step 18.3: Tear down the sandbox**

```sh
cd ~   # leave the sandbox before deleting it
rm -rf /tmp/engram-plugin-test-$DATE
rm -f /tmp/hooktrace-plugin /tmp/hooktrace-cli /tmp/claude-stderr.log
```

- [ ] **Step 18.4: Push commits to origin**

```sh
cd /home/cdm/engram
git push origin v1.7-plugin
```

Expected: push succeeds. If the branch doesn't exist on origin yet (new branch), push with `-u origin v1.7-plugin`.

- [ ] **Step 18.5: Final post-session Engram checkpoint (optional but recommended)**

Use `mcp__engram__save_checkpoint` to save a session summary so the next Engram briefing reads cleanly. Content: brief summary of Phase 2b outcomes and readiness for Phase 3.

---

## Done

At this point:
- Phase 2b is complete.
- `v1.7-plugin` is green and pushed.
- Engram has a clean record of what was verified, with Claude Code version stamps.
- The plugin either works as originally assumed (U1-A) or has been fixed to work (U1-B/C/D), with the fix covered by the re-run of the full baseline.
- Phase 3 (remaining MVP skills: `post-decision`, `query`, `checkpoint-save`, `checkpoint-restore`) can start on the same branch in the next session.

---

## Resumption notes

If the session is interrupted partway through:

- Before restarting, read `/tmp/engram-plugin-test-$DATE/findings.md` to see which tasks completed.
- Each task is idempotent if you re-run it, except Task 7's `.mcp.json` edit — check `git status plugin/.mcp.json` before re-running.
- The trap in Task 2 Step 2.3 only fires on normal shell exit; if the shell was killed, manually verify `plugin/testlink`, `/tmp/hooktrace-*`, and `plugin/skills/test-mcp/` are gone.
- The four HIGH warnings stay open in Engram until Task 16 Step 16.1 — a partial run leaves them open, which is the correct behavior.
