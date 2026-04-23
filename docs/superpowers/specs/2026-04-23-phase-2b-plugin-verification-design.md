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
touch README.md   # something harmless to Edit for hook tests
```

No `git init` — Engram doesn't require a git repo to operate.

**Pre-flight: confirm no leftover U4 artifact.** Before launch, verify the test symlink from a prior run isn't still present:
```sh
test -e /home/cdm/engram/plugin/testlink && \
  echo "ERROR: stale U4 test artifact — remove before starting" && exit 1
```

**Install a crash-safety trap in the launch shell** so a session abort doesn't leave the plugin tree polluted:
```sh
trap 'rm -f /home/cdm/engram/plugin/testlink /tmp/hooktrace-plugin /tmp/hooktrace-cli' EXIT
```

Launch Claude Code in the sandbox:

```sh
source /home/cdm/engram/.venv/bin/activate   # puts engram + engram-mcp on PATH
claude --plugin-dir /home/cdm/engram/plugin
```

**PATH note:** `engram` and `engram-mcp` are installed editable into `/home/cdm/engram/.venv/bin`. The shell that launches Claude Code must have that directory on `PATH` (either by activating the venv or exporting it explicitly). If `which engram` from the sandbox shell returns nothing, the hooks and MCP server will silently fail and every test below will appear broken.

**Teardown:** `rm -rf /tmp/engram-plugin-test-$DATE`, plus the EXIT trap clears `plugin/testlink` and the hook trace files. Findings live in the real Engram DB (see "Recording" below), not in the sandbox.

### Pre-test: U1-E sanity check (outside Claude Code)

Before launching Claude Code, rule out the "engram-mcp ignores `ENGRAM_PROJECT_DIR`" failure mode — otherwise a later U1-A "pass" could mask a regression. This exercises the EventStore instantiation path the MCP server uses, without needing an MCP client:

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
_ = store.conn   # force schema init
store.close()
print('project_dir:', pd)
print('db exists:', db.exists())
"
ls -la /tmp/engram-u1e-decoy/.engram/
rm -rf /tmp/engram-u1e-decoy
```

Expect `project_dir: /tmp/engram-u1e-decoy` and the DB to exist at that path. If the env var is honored, engram-mcp will behave the same way inside Claude Code's MCP spawn. If the DB lands somewhere else (e.g., `$(pwd)/.engram/events.db`), stop Phase 2b and fix `engram-mcp` first — U1 branches are not interpretable until this works.

## Test matrix

Each test has a **probe**, **pass criterion**, and **fail action** (FIX = address in this session before moving on; DEFER = record and continue).

### Baseline smokes

The baseline smokes gate the unknowns. A failure here usually means "the plugin didn't install or wire up correctly" and must be diagnosed before interpreting unknown-test results.

#### S1 — Plugin loads

**Probe:** Launch Claude Code with `--debug --plugin-dir /home/cdm/engram/plugin 2>/tmp/claude-stderr.log` and:

1. Confirm nothing prefixed `error:`, `Error:`, or `plugin load failed` appears on stderr (`grep -iE 'error|failed' /tmp/claude-stderr.log` should return nothing plugin-related).
2. Run `/plugin list`; the `engram` entry must be present with no "failed"/"error" annotation.
3. Run `/plugin` → Errors tab (if such a UI exists in this Claude Code version) — must be empty for engram.

**Pass:** All three clean.

**Fail action:** **FIX**. Almost certainly a `plugin.json` schema issue. Blocker for everything downstream.

#### S2 — Skill discovered

**Probe:** Type `/` in the Claude Code prompt; `/engram:briefing` should appear in completion. Run `/engram:briefing`. Output should be a project briefing (note: the sandbox `.engram/events.db` is empty, so the briefing will be sparse — a minimal header is still a pass).

**Pass:** Skill discoverable and runs without error.

**Fail action:** **FIX**. Skill discovery is broken, or `allowed-tools: Bash(engram *)` syntax didn't parse. Blocker.

#### S3 — MCP connects *and resolves the right project dir*

This test also gates U1. A false pass here (MCP connected but pointing at the wrong dir) would cascade and make S4–S6 appear broken for the same root cause. So S3 does three things at once:

**Probes (run all three, record all three):**

1. **MCP connected.** Run `/mcp`; confirm `engram` is listed as connected.
2. **Spawned cwd.** Find the running server: `ps auxf | grep engram-mcp` → note PID → `readlink /proc/<PID>/cwd`. Record the exact path.
3. **Project dir as the server sees it.** From inside Claude Code, call the MCP tool `mcp__engram__status` and note the `project_dir` / DB path it reports. Also: `find /tmp/engram-plugin-test-$DATE ~/.claude/plugins/cache ~/.engram /home/cdm/engram -type d -name .engram -newer /tmp/engram-plugin-test-$DATE 2>/dev/null` to locate any `.engram/` dir the server just created. There should be exactly one, inside the sandbox.

**Pass:** (1) connected, (2) cwd is the sandbox dir, (3) project_dir is the sandbox dir, and the `.engram/` dir scan finds exactly one match inside the sandbox.

**Fail action:** **FIX**, then jump straight to U1 to pick the correct outcome branch. Do NOT proceed to S4–S6 first — they'll misdiagnose. Once U1 is fixed, re-run S3 until green, then continue.

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

The plugin's `.mcp.json` currently sets `ENGRAM_PROJECT_DIR=${PWD}`. Docs show `${CLAUDE_PROJECT_DIR}` in hook examples but do not confirm any variable expansion in MCP env vars.

**Diagnosis is already done by S3** (connected? spawned cwd? reported project_dir?). Read the S3 probe outputs and map them to one of the five outcomes below. Then apply the matching fix.

**U1-A: `${PWD}` expands to the sandbox dir.** S3 project_dir = sandbox. **No change.**

**U1-B: `${PWD}` does not expand, but `engram-mcp` was spawned in the user's CWD.** S3: project_dir literally reads `${PWD}` (unexpanded) OR `engram-mcp` logs an error about that path. `engram-mcp` would default to `os.getcwd()` if we removed the env var (confirmed in `src/engram/mcp_server.py:30`). **Fix: drop the `env` block entirely from `.mcp.json`.** Simpler than today.

**U1-C: `${PWD}` does not expand AND `engram-mcp` is spawned from the plugin cache directory.** S3: spawned cwd = `~/.claude/plugins/cache/...`, project_dir literal `${PWD}` or that same cache path. Need a replacement. Try in order:
  1. `${CLAUDE_PROJECT_DIR}` as the env value (redeploy, re-test S3).
  2. If that also doesn't work, ship a shell wrapper at `plugin/bin/engram-mcp-wrapper` (bash script that reads `$CLAUDE_PROJECT_DIR` or derives CWD and execs `engram-mcp`). Update `.mcp.json` to use `${CLAUDE_PLUGIN_ROOT}/bin/engram-mcp-wrapper`.

**U1-D: `${PWD}` expands, but to the wrong value.** S3: project_dir is a *real* path but not the sandbox (e.g., the user's `$HOME`, the plugin cache, or the directory Claude was launched from if Claude internally changed cwd). This is the subtle one — it would produce a working plugin that silently writes to the wrong DB. Fix: same as U1-C — switch to `${CLAUDE_PROJECT_DIR}` (which is documented to always be the user's project root for hooks; test if it's available in MCP env vars too). Wrapper is the fallback.

**U1-E: engram-mcp ignores the env var.** The pre-test (sandbox setup → U1-E sanity check) should have ruled this out before launch. If the pre-test passed and S3 still shows the wrong project_dir, U1-E isn't the cause — skip. If the pre-test failed, stop Phase 2b and fix `engram-mcp` first.

**Fail action:** **FIX**. After each `.mcp.json` change, fully restart Claude Code (not `/reload-plugins` — plugin manifest changes need a fresh launch) and **re-run the full S1–S6 sequence**, not just S3. A change that fixes S3 could regress S1, S2, or S6 (e.g., a wrapper script with the wrong shebang fails silently at startup). Loop until S1–S6 are all green in the final state.

#### U2 — Hook dedup with CLI-installed hooks

**Why the naive approach doesn't work:** counting `event_type='mutation'` rows before/after an edit is unreliable because (a) Claude may issue multiple tool_use blocks per logical edit, (b) a hypothetical dedup-by-payload in the store would hide true double-firing, (c) if the two hook invocations race on SQLite WAL, one could drop. The DB is downstream of too many layers to trust as the signal.

**Instead: count trace-file lines written by distinguishable hook signatures.**

**Probe:**

1. Exit Claude Code.
2. Truncate trace files: `: > /tmp/hooktrace-plugin; : > /tmp/hooktrace-cli`.
3. Temporarily edit `plugin/hooks/hooks.json` so the PostToolUse Edit hook wraps the engram call:
   ```
   "command": "sh -c 'echo plugin >> /tmp/hooktrace-plugin; engram hook post-tool-use'"
   ```
4. In the sandbox, run `engram hooks install`, then manually edit the written `.claude/settings.json` so its PostToolUse Edit hook also wraps distinguishably:
   ```
   "command": "sh -c 'echo cli >> /tmp/hooktrace-cli; engram hook post-tool-use'"
   ```
5. Relaunch with `--plugin-dir /home/cdm/engram/plugin`.
6. Ask Claude to make exactly one edit to README.md. Wait for completion.
7. Inspect traces:
   ```sh
   echo plugin: $(wc -l < /tmp/hooktrace-plugin)
   echo cli:    $(wc -l < /tmp/hooktrace-cli)
   ```

**Outcome table:**

| plugin trace | cli trace | Interpretation |
|---|---|---|
| 1 | 0 | Plugin hook wins; CLI hook suppressed (dedup by source preference) |
| 0 | 1 | CLI hook wins; plugin hook suppressed |
| 1 | 1 | **Double-fire** — both sources invoke independently |
| 0 | 0 | Neither fired — misconfiguration; investigate before interpreting |
| ≥2 in either | | Claude issued multiple tool_use blocks for one edit; divide by N or simplify the edit prompt |

**Cleanup after U2:** revert `plugin/hooks/hooks.json` (git checkout or manual restore) and run `engram hooks uninstall` in the sandbox. Truncate the trace files.

**Action:** **DEFER**. Record the outcome in Engram. If double-fire: release notes must warn users to uninstall CLI hooks first, and Phase 4 should teach the CLI installer to detect plugin presence. If one-source-wins: record which, because that determines which install path is canonical.

#### U3 — Skill can pre-approve an MCP tool

`allowed-tools` in a skill frontmatter is *not* the same thing as the user-facing permission prompt. The prompt is gated by `.claude/settings.json` `permissions.allow` (or the session allowlist). `allowed-tools` controls what the skill itself is permitted to invoke — a different axis. So U3 tests three orthogonal questions:

- **Q1 (loading):** Does a skill with `allowed-tools: mcp__engram__status` in its frontmatter load without parse error?
- **Q2 (resolution):** When the skill runs, can Claude resolve and invoke the MCP tool `mcp__engram__status`?
- **Q3 (prompt suppression):** Does `allowed-tools` alone suppress the user-facing permission prompt, or is a `permissions.allow` entry in `.claude/settings.json` also required?

**Probe:**

1. Create `plugin/skills/test-mcp/SKILL.md`:
   ```markdown
   ---
   name: test-mcp
   description: Test whether a skill can invoke an MCP tool.
   allowed-tools: mcp__engram__status
   ---

   Run the Engram MCP status tool and show the result.
   ```
2. **Exit Claude Code completely, then relaunch** with `--plugin-dir`. Do not rely on `/reload-plugins` — it is under-documented and may cache the plugin manifest from launch. A full relaunch is the documented way to pick up a new skill.
3. Ensure `.claude/settings.json` in the sandbox has NO `permissions.allow` entry for `mcp__engram__status` (should already be clean; verify with `cat .claude/settings.json | grep -i engram_status`).
4. Invoke `/engram:test-mcp`. Observe:
   - Q1: did the slash command appear in completion (skill loaded)?
   - Q2: did Claude attempt to call `mcp__engram__status`?
   - Q3: did a permission prompt appear before the call?
5. **Exit and relaunch**, this time after adding `mcp__engram__status` to `permissions.allow` in the sandbox `.claude/settings.json`. Re-invoke `/engram:test-mcp` and observe the Q3 axis again.

**Outcomes to record** (any combination possible):

- Q1 fail (skill didn't load): `allowed-tools` frontmatter syntax doesn't accept MCP tool names as written. The Bash shell-out path in the current briefing skill is unaffected.
- Q1 pass + Q2 fail: skill loaded but the MCP tool name isn't recognized in this context.
- Q1 pass + Q2 pass + Q3 (prompt suppressed without `permissions.allow`): `allowed-tools` alone is sufficient — cleanest outcome for native MCP invocation.
- Q1 pass + Q2 pass + Q3 (prompt only suppressed when `permissions.allow` is also present): native invocation requires both mechanisms. Usable, but we'd also need to ship a `permissions.allow` recommendation.
- Q1 pass + Q2 pass + Q3 (prompt fires even with `permissions.allow`): unusable for native invocation — Bash shell-out remains the only path.

**Cleanup:** remove `plugin/skills/test-mcp/` after recording. Remove the `permissions.allow` test entry from sandbox settings.

**Action:** **DEFER**. Current `briefing` skill uses Bash shell-out, which is unaffected regardless of outcome. Record the outcome matrix as a discovery; Phase 4 (or v1.8) decides whether to switch any skills to native MCP invocation.

#### U4 — Symlink survival in plugin cache

Docs claim symlinks are preserved across the plugin install (which copies the plugin directory into `~/.claude/plugins/cache/{id}/{version}/`). Untested for our case.

**Probe:**
1. Pre-check (belt + braces over the sandbox-setup pre-check): verify no stale testlink — `test -e /home/cdm/engram/plugin/testlink && echo STALE && exit 1`.
2. Create a symlink inside the plugin: `ln -s ../README.md /home/cdm/engram/plugin/testlink`.
3. **Caveat about `--plugin-dir`:** dev mode may run the plugin directly from the source directory without copying into `~/.claude/plugins/cache/`. Before testing, snapshot the cache: `find ~/.claude/plugins/cache -maxdepth 4 -name '*engram*' 2>/dev/null` — if nothing matches, dev mode is in-place and the symlink question is moot (nothing gets copied, so survival is trivial). In that case, perform a real install via `/plugin install <local-path>` or `claude plugin install` (whichever the in-session UI supports) to exercise the cache-copy path.
4. **Exit Claude Code and relaunch** with `--plugin-dir`. Do not rely on `/reload-plugins` here either — for plugin filesystem changes the cache copy only re-runs at a cold start. (If `/reload-plugins` later proves to pick up file changes, we can revisit, but the safe path is a full relaunch.)
5. Check the installed copy:
```sh
find ~/.claude/plugins/cache -name testlink -exec ls -la {} \;
```
(The cache path layout is `~/.claude/plugins/cache/{id}/{version}/` but the exact layout isn't worth memorizing — `find` is more robust.)

**Outcomes:**
- Cache has no engram dir at all (dev mode bypasses cache) → record this as the finding and skip the symlink question.
- Still a symlink in cache → preserved (pass).
- Regular file with content of target → copied-through (acceptable for many uses but breaks dynamic targets).
- Missing from cache → not preserved.

**Cleanup:** `rm /home/cdm/engram/plugin/testlink`. The EXIT trap installed at sandbox setup will also remove it if the session aborts, but do it explicitly so we don't depend on the trap firing.

**Action:** **DEFER**. We don't currently use symlinks in the plugin. Record the finding for future reference.

## Recording findings

Every test result flows back into the real Engram DB (not the sandbox DB — the real one at `/home/cdm/engram/.engram/events.db`).

**Capture the Claude Code version first:** run `claude --version` and record the output. Every discovery posted below MUST include this version in its body (e.g., "observed 2026-04-23 with Claude Code vX.Y.Z"). Plugin behavior like `${PWD}` expansion, hook merge semantics, and permission-prompt gating are harness-version-dependent facts; a discovery without a version stamp rots silently the next time Claude Code ships.

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

- [ ] All six baseline smokes (S1–S6) pass **in the final state** (i.e., after any U1 fix is applied and the plugin relaunched — not just the first time through).
- [ ] U1 is resolved (one of A–E picked, with any fix applied and verified via the full S1–S6 re-run).
- [ ] U2, U3, U4 findings are recorded as Engram discoveries (or warnings if a divergence was serious enough to warrant one).
- [ ] All four HIGH "UNVERIFIED" warnings from 2026-04-21 are resolved in Engram.
- [ ] Every posted discovery includes the Claude Code version observed.
- [ ] No stray `.engram/` directories exist outside the sandbox. Verify with:
  ```sh
  find /home /tmp ~/.claude -maxdepth 6 -type d -name .engram 2>/dev/null
  ```
  The only matches should be `/home/cdm/engram/.engram` (the real project DB) and `/tmp/engram-plugin-test-$DATE/.engram` (the sandbox, about to be torn down). Anything else — especially under `~/.claude/plugins/cache/...` or `$HOME/.engram` — means a U1 fallback silently wrote to the wrong place and needs investigation before closing Phase 2b.
- [ ] `docs/ROADMAP.md#17` is updated to reflect Phase 2b outcomes.
- [ ] Sandbox `/tmp/engram-plugin-test-$DATE` is torn down.
- [ ] Throwaway test skill `plugin/skills/test-mcp/` and test symlink `plugin/testlink` are removed (trap + explicit `rm` in the procedure).
- [ ] `plugin/hooks/hooks.json` reverted to its committed state (U2 wrapped it temporarily).
- [ ] Trace files `/tmp/hooktrace-plugin` and `/tmp/hooktrace-cli` removed.

When all gates pass, Phase 3 (remaining MVP skills: `post-decision`, `query`, `checkpoint-save`, `checkpoint-restore`) can proceed on the same branch.

## Out of scope

- Writing the remaining MVP skills (Phase 3).
- Adding `ENGRAM_CONTEXT_DIRS` configuration (Phase 4).
- Subscribing to new hook events like PreCompact/PostCompact (deferred beyond v1.7).
- Marketplace submission (deferred per the 2026-04-21 decision).
- Any per-subagent event capture work (deferred beyond v1.7).
