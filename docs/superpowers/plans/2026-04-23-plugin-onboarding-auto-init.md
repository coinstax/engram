# Plugin Onboarding Auto-Init Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Phase 2b onboarding gap so a user can install the Engram plugin into any project and have `/engram:briefing` + `mcp__engram__*` work on first launch, without running `engram init` manually and without the plugin modifying the user's tracked `CLAUDE.md`.

**Architecture:** Factor the existing `engram init` body into a reusable helper in a new `src/engram/init.py` module. The CLI keeps its full behavior (git seeding + `CLAUDE.md` write). The SessionStart hook calls the same helper *without* `CLAUDE.md` write when `.engram/events.db` is missing, because the plugin already carries agent-facing guidance through the FastMCP `instructions` field (`mcp_server.py:21-25`) and SKILL.md frontmatter — making the `CLAUDE.md` snippet redundant in the plugin path. This is "Option C-lite" from the Phase 2b discussion.

**Tech Stack:** Python 3.12+, Click (CLI), pytest, existing `EventStore` + `GitBootstrapper` modules.

---

## Background — chosen approach

**Option C-lite** was chosen over:
- **A** (docs only) — leaves the "install and go" experience broken; first `/engram:briefing` errors out.
- **B** (`store.initialize()` only) — skips git history seeding, so the first briefing is empty (defeats the whole bootstrap feature shipped in v1.0).
- **C full** (run the complete `engram init`, including `_auto_write_claude_md`) — rejected because plugins silently modifying a user's tracked `CLAUDE.md` on install is not normal plugin behavior. The `FastMCP(instructions=...)` string and SKILL.md frontmatter already deliver agent guidance when the plugin is loaded; the `CLAUDE.md` append is redundant in the plugin path.

The hook path initializes the schema, seeds from git, sets meta — everything except the `CLAUDE.md` write. The CLI `engram init` command retains all its existing behavior because the user explicitly asked for it.

## File Structure

**Create:**
- `src/engram/init.py` — shared `perform_init()` helper + `InitResult` dataclass. Single responsibility: do all the filesystem/DB/git-bootstrap steps of initialization, return structured result. Does NOT touch `CLAUDE.md`.
- `tests/test_init.py` — unit tests for `perform_init()`.

**Modify:**
- `src/engram/cli.py` — `engram init` command delegates to `perform_init()`; keeps the `_auto_write_claude_md()` call afterward.
- `src/engram/hooks.py` — `handle_session_start()` calls `perform_init()` when `events.db` is missing, prepends a one-line init banner to the returned briefing.
- `tests/test_hooks.py` — replace `test_session_start_no_engram_returns_empty` with auto-init coverage; add `CLAUDE.md`-not-touched assertion.
- `docs/ROADMAP.md` — mark onboarding-gap resolution.
- `CHANGELOG.md` — v1.7.0 "Unreleased" entry.
- `plugin/README.md` — document first-session auto-init behavior and note CLAUDE.md is untouched.

---

## Task 1: Record the C-lite decision in Engram

**Why first:** locks the choice in project memory before any code changes, so future sessions (and reviewers) see the rationale.

- [ ] **Step 1: Post the decision event via Engram MCP**

Use `mcp__engram__post_event` with:
- `event_type`: `"decision"`
- `priority`: `"high"`
- `scope`: `["src/engram/hooks.py", "src/engram/init.py", "plugin/"]`
- `content` (verbatim):

```
Plugin onboarding gap resolved with Option C-lite: SessionStart hook auto-runs engram init WITHOUT the CLAUDE.md append. Rationale: (1) users expect install-and-go after adding the plugin; (2) option B (schema-only init) loses git-history seeding and defeats the v1.0 bootstrap feature; (3) option C full is rejected because plugins silently modifying a user's tracked CLAUDE.md on install is not normal plugin behavior; (4) the FastMCP(instructions=...) string in mcp_server.py:21-25 and SKILL.md frontmatter already deliver agent-facing guidance when the plugin is loaded, so the CLAUDE.md snippet is redundant in the plugin path. Implementation: factor engram init body into src/engram/init.py::perform_init, call from both cli.py (with CLAUDE.md write) and hooks.py (without).
```

- [ ] **Step 2: Verify the event was recorded**

Use `mcp__engram__query` with `text="C-lite"` and confirm one matching decision event exists in the current project.

---

## Task 2: Create `perform_init()` helper (TDD)

**Files:**
- Create: `src/engram/init.py`
- Create: `tests/test_init.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_init.py`:

```python
"""Tests for the shared init helper."""

import subprocess
from pathlib import Path

import pytest

from engram.init import InitResult, perform_init
from engram.store import EventStore


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    """A bare git project with one commit and a README — no .engram/."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "--allow-empty", "-q", "-m", "initial commit"],
        cwd=tmp_path, check=True,
    )
    (tmp_path / "README.md").write_text("# testproj\n")
    return tmp_path


def test_perform_init_creates_engram_dir_and_db(tmp_path):
    result = perform_init(tmp_path)
    assert isinstance(result, InitResult)
    assert (tmp_path / ".engram" / "events.db").exists()
    assert result.already_initialized is False


def test_perform_init_is_idempotent(tmp_path):
    first = perform_init(tmp_path)
    second = perform_init(tmp_path)
    assert first.already_initialized is False
    assert second.already_initialized is True


def test_perform_init_non_git_project_falls_back_to_dirname(tmp_path):
    result = perform_init(tmp_path)
    assert result.project_name == tmp_path.name
    assert result.events_seeded == 0


def test_perform_init_seeds_from_git_history(git_project):
    result = perform_init(git_project)
    # Git repo has at least one commit; bootstrapper mines it plus docs.
    assert result.events_seeded >= 1
    assert result.already_initialized is False


def test_perform_init_does_not_touch_claude_md(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# Pre-existing content\n")
    pre = claude_md.read_text()

    perform_init(tmp_path)

    assert claude_md.read_text() == pre


def test_perform_init_does_not_create_claude_md(tmp_path):
    perform_init(tmp_path)
    assert not (tmp_path / "CLAUDE.md").exists()


def test_perform_init_sets_project_name_and_initialized_at(tmp_path):
    perform_init(tmp_path)
    store = EventStore(tmp_path / ".engram" / "events.db")
    try:
        assert store.get_meta("project_name") == tmp_path.name
        assert store.get_meta("initialized_at") is not None
    finally:
        store.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_init.py -v`
Expected: ModuleNotFoundError / ImportError for `engram.init`.

- [ ] **Step 3: Implement `src/engram/init.py`**

```python
"""Shared Engram initialization logic — used by CLI and SessionStart hook."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from engram.bootstrap import GitBootstrapper
from engram.store import EventStore

ENGRAM_DIR = ".engram"
DB_NAME = "events.db"


@dataclass
class InitResult:
    """Outcome of perform_init()."""
    project_name: str
    events_seeded: int
    already_initialized: bool


def perform_init(project_dir: Path, *, max_commits: int = 100) -> InitResult:
    """Initialize Engram in a project directory. Idempotent.

    Creates `.engram/events.db`, sets schema, bootstraps from git history
    (when the project is a git repo), and records `project_name` +
    `initialized_at` meta. Returns `already_initialized=True` without
    further side effects when the DB already exists.

    NOTE: does NOT modify CLAUDE.md. Callers that want the CLAUDE.md
    append (e.g. `engram init` CLI) should invoke _auto_write_claude_md
    themselves after calling this helper.
    """
    engram_dir = project_dir / ENGRAM_DIR
    db_path = engram_dir / DB_NAME

    if db_path.exists():
        store = EventStore(db_path)
        try:
            project_name = store.get_meta("project_name") or project_dir.name
        finally:
            store.close()
        return InitResult(
            project_name=project_name,
            events_seeded=0,
            already_initialized=True,
        )

    engram_dir.mkdir(parents=True, exist_ok=True)
    store = EventStore(db_path)
    try:
        store.initialize()

        event_count = 0
        try:
            bootstrapper = GitBootstrapper(project_dir)
            project_name = bootstrapper.detect_project_name()
            events = bootstrapper.mine_history(max_commits=max_commits)
            if events:
                event_count = store.insert_batch(events)
        except ValueError:
            # Not a git repo — still initialize, just without seed data.
            project_name = project_dir.name

        store.set_meta("project_name", project_name)
        store.set_meta("initialized_at", datetime.now(timezone.utc).isoformat())
    finally:
        store.close()

    return InitResult(
        project_name=project_name,
        events_seeded=event_count,
        already_initialized=False,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_init.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/engram/init.py tests/test_init.py
git commit -m "feat(init): factor init logic into reusable perform_init helper"
```

---

## Task 3: Refactor `engram init` CLI to delegate to the helper

**Files:**
- Modify: `src/engram/cli.py:93-132`

- [ ] **Step 1: Run existing CLI init tests to establish green baseline**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v -k "init"`
Expected: existing init tests pass on current implementation.

- [ ] **Step 2: Replace the init command body**

In `src/engram/cli.py`, replace the full body of the `init` function (lines 93-132) with a delegation to `perform_init`. The CLAUDE.md auto-write behavior MUST be preserved so manual `engram init` users see no change.

Add import near the top of `cli.py` (after the other `engram.*` imports):

```python
from engram.init import perform_init
```

Replace the function body with:

```python
@cli.command()
@click.option("--max-commits", default=100, help="Max git commits to mine")
@click.pass_context
def init(ctx, max_commits):
    """Initialize Engram in this project. Seeds from git history."""
    project = ctx.obj["project"]

    result = perform_init(project, max_commits=max_commits)

    if result.already_initialized:
        click.echo(f"Engram already initialized in {project}")
        return

    click.echo(
        f"Engram initialized for '{result.project_name}'. "
        f"{result.events_seeded} events seeded from git history."
    )
    claude_msg = _auto_write_claude_md(project)
    click.echo(claude_msg)
    click.echo(
        "Run 'engram hooks install' to enable passive observation via Claude Code hooks."
    )
```

Also remove the now-dead imports inside the old function body (`from engram.bootstrap import GitBootstrapper` at top of file is still needed? Check — yes, nothing else in cli.py uses it; remove that import line too if unused elsewhere).

- [ ] **Step 3: Verify CLI tests still pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v -k "init"`
Expected: same set of init tests pass.

- [ ] **Step 4: Run the full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all tests pass; no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/engram/cli.py
git commit -m "refactor(cli): delegate engram init to perform_init helper"
```

---

## Task 4: Auto-init from SessionStart hook

**Files:**
- Modify: `src/engram/hooks.py:352-381` (`handle_session_start`)
- Modify: `tests/test_hooks.py:211-216` (replace old test, add CLAUDE.md assertion)

- [ ] **Step 1: Write failing tests**

In `tests/test_hooks.py`, delete the existing `test_session_start_no_engram_returns_empty` (lines 211-216) and add in its place:

```python
    def test_session_start_no_engram_auto_inits(self, tmp_path):
        output = handle_session_start(
            {"session_id": "sess-abc", "cwd": str(tmp_path)},
            tmp_path,
        )
        # Auto-init should have created the DB
        assert (tmp_path / ".engram" / "events.db").exists()
        # Output includes a briefing (even if sparse on a fresh non-git dir)
        assert "Engram" in output

    def test_session_start_auto_init_does_not_touch_claude_md(self, tmp_path):
        # Pre-existing CLAUDE.md must not be modified
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# User's own content\n")
        pre = claude_md.read_text()

        handle_session_start(
            {"session_id": "sess-abc", "cwd": str(tmp_path)},
            tmp_path,
        )

        assert claude_md.read_text() == pre

    def test_session_start_auto_init_does_not_create_claude_md(self, tmp_path):
        handle_session_start(
            {"session_id": "sess-abc", "cwd": str(tmp_path)},
            tmp_path,
        )
        assert not (tmp_path / "CLAUDE.md").exists()

    def test_session_start_auto_init_includes_banner(self, tmp_path):
        output = handle_session_start(
            {"session_id": "sess-abc", "cwd": str(tmp_path)},
            tmp_path,
        )
        # Banner announces first-run init so the user knows what happened.
        assert "initialized" in output.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_hooks.py::TestSessionStartHook -v`
Expected: the four new tests fail — `handle_session_start` currently returns `""` when `.engram/` is missing, so `.engram/events.db` is never created and "initialized" is not in the output.

- [ ] **Step 3: Modify `handle_session_start` in `src/engram/hooks.py`**

Add import at the top of `hooks.py` alongside the other `engram.*` imports:

```python
from engram.init import perform_init
```

Replace the body of `handle_session_start` (lines 352-381) with:

```python
def handle_session_start(stdin_data: dict, project_dir: Path) -> str:
    """Handle SessionStart hook. Auto-inits if needed, registers session, returns briefing.

    When `.engram/events.db` is missing we initialize it — git-history
    bootstrap and meta are populated. CLAUDE.md is intentionally NOT
    modified: the plugin already carries agent guidance via FastMCP
    instructions and SKILL.md frontmatter, so we leave the user's
    tracked CLAUDE.md alone.
    """
    db_path = project_dir / ENGRAM_DIR / DB_NAME
    init_banner = ""
    if not db_path.exists():
        try:
            result = perform_init(project_dir)
            if not result.already_initialized:
                init_banner = (
                    f"Engram initialized for '{result.project_name}'. "
                    f"{result.events_seeded} events seeded from git history.\n\n"
                )
        except OSError:
            # Filesystem denied init (read-only mount, etc.) — fail quiet.
            return ""

    store = _get_store(project_dir)
    if not store:
        return ""

    try:
        agent_id = "claude-code"

        store.cleanup_stale_sessions()

        active = store.get_active_session(agent_id)
        if active:
            store.end_session(active.id)

        project_name = store.get_meta("project_name") or project_dir.name
        sess = Session(
            id="", agent_id=agent_id,
            focus=f"Working on {project_name}",
        )
        store.insert_session(sess)

        gen = BriefingGenerator(store)
        result = gen.generate()
        return init_banner + format_briefing_compact(result)
    finally:
        store.close()
```

- [ ] **Step 4: Run the hook tests**

Run: `.venv/bin/python -m pytest tests/test_hooks.py::TestSessionStartHook -v`
Expected: all four new tests pass; the existing `test_session_start_returns_briefing` still passes.

- [ ] **Step 5: Run the full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/engram/hooks.py tests/test_hooks.py
git commit -m "feat(hooks): auto-init Engram on first SessionStart without CLAUDE.md write"
```

---

## Task 5: Docs + CHANGELOG + plugin README

**Files:**
- Modify: `docs/ROADMAP.md`
- Modify: `CHANGELOG.md`
- Modify: `plugin/README.md`

- [ ] **Step 1: Mark onboarding gap resolved in `docs/ROADMAP.md`**

Locate the onboarding-gap bullet (approximately `docs/ROADMAP.md:119`):

```
5. **Onboarding gap: plugin does not auto-init.** A user installing the plugin and invoking `/engram:briefing` or `mcp__engram__status` gets "Engram not initialized" until they manually run `engram init`. Needs a decision before v1.7.0 release: (A) document manual init in plugin README/skill, (B) SessionStart hook auto-inits without git seeding, (C) SessionStart hook runs full `engram init`. Recorded as HIGH discovery in Engram.
```

Replace it with:

```
5. **Onboarding gap resolved (2026-04-23, Option C-lite).** SessionStart hook now auto-runs init when `.engram/events.db` is missing: creates the DB, seeds from git history, sets meta. CLAUDE.md is intentionally left alone — the plugin carries agent guidance via the FastMCP `instructions` field (`src/engram/mcp_server.py:21-25`) and SKILL.md frontmatter, making the CLAUDE.md snippet redundant in the plugin path. Manual `engram init` (CLI) retains full behavior including the CLAUDE.md auto-write, since the user explicitly asked for it. See `src/engram/init.py` for the shared helper.
```

- [ ] **Step 2: Add CHANGELOG entry**

Add under the "Unreleased" / v1.7.0 section of `CHANGELOG.md` (if no Unreleased section yet, create one at the top):

```markdown
### Added
- **Plugin auto-init on SessionStart** — when the Engram Claude Code plugin is installed into a project that has not yet been initialized, the SessionStart hook now runs the equivalent of `engram init` automatically (creating `.engram/`, seeding from git history, setting project meta) so `/engram:briefing` and the MCP tools work on first launch. CLAUDE.md is intentionally not modified from the plugin path — agent guidance is already delivered via the FastMCP `instructions` field and plugin SKILL.md frontmatter.
- `src/engram/init.py` — shared `perform_init()` helper extracted from the `engram init` CLI; used by both the CLI command and the SessionStart hook.
```

- [ ] **Step 3: Update `plugin/README.md`**

Near the install / first-run instructions, add:

```markdown
## First run

On first launch in a project that has no `.engram/` directory, the plugin's SessionStart hook initializes Engram automatically: creates `.engram/events.db`, seeds events from the last 100 git commits, and registers a session. The first briefing announces this with a one-line banner.

The plugin does **not** modify your `CLAUDE.md`. Agent-facing guidance is delivered through the MCP server's `instructions` field and the plugin's SKILL.md files. If you later want the `CLAUDE.md` snippet (e.g. for non-plugin / headless use), run `engram init` manually — it detects existing `.engram/` and appends the snippet only.
```

Note: the last sentence describes a CLI behavior that should already be true after Task 3 (the CLI prints `"Engram already initialized in <path>"` and returns early, so it does NOT append the snippet in that case). If the implementer wants CLI re-run to still append the CLAUDE.md snippet on an already-initialized project, that's a separate enhancement — out of scope here. Confirm the CLI behavior matches the docs claim before committing; if there's a mismatch, prefer tightening the README wording to match the code rather than expanding scope.

- [ ] **Step 4: Commit**

```bash
git add docs/ROADMAP.md CHANGELOG.md plugin/README.md
git commit -m "docs: record plugin auto-init resolution and first-run behavior"
```

---

## Task 6: End-to-end sandbox verification

**Why:** Phase 2b verified plugin wiring against the old (broken) onboarding behavior. We need to re-verify through the full plugin path — Claude Code → plugin SessionStart hook → auto-init — on a clean sandbox.

- [ ] **Step 1: Reset the sandbox**

```bash
cd "$HOME/engram-test"    # or any scratch directory outside the engram source tree
rm -rf .engram .claude CLAUDE.md
ls -la
```
Expected: no `.engram/`, no `.claude/`, no `CLAUDE.md` (or only the user's pre-existing version — preserve it before deletion if they care).

- [ ] **Step 2: Launch Claude Code with the plugin in dev mode**

```bash
cd "$HOME/engram-test"
claude --debug --plugin-dir "$ENGRAM_REPO/plugin"   # $ENGRAM_REPO = absolute path to the engram checkout
```

- [ ] **Step 3: In the Claude Code session, verify auto-init happened**

Inside the session, check:

```
mcp__engram__status
```

Expected: returns a valid status payload (project_name = "engram-test" or the directory name, total_events > 0 if there's git history, non-zero db_size_bytes). NOT an error about "Engram not initialized".

```
!ls -la .engram/
```

Expected: `.engram/events.db` exists.

```
!ls -la CLAUDE.md 2>&1
```

Expected: `No such file or directory` — the plugin did not create CLAUDE.md.

- [ ] **Step 4: Verify `/engram:briefing` works**

Invoke the slash command `/engram:briefing`. Expected output: a briefing section (possibly with the init banner on first invocation) — not an error.

- [ ] **Step 5: Exit the sandbox and record the verification**

Post an Engram event in THIS project (not the sandbox):

```
mcp__engram__post_event with:
  event_type: "discovery"
  scope: ["plugin/", "src/engram/hooks.py", "src/engram/init.py"]
  content: "Phase 2b onboarding gap fix verified end-to-end in the scratch sandbox on <YYYY-MM-DD> with Claude Code <version>. Plugin install → first SessionStart auto-created .engram/events.db, seeded git history, did not touch CLAUDE.md. mcp__engram__status and /engram:briefing both worked on first invocation without prior engram init."
```

- [ ] **Step 6: No code commit here — verification only**

Return a short status to the user describing what was verified and any anomalies.

---

## Self-Review Notes

- **Spec coverage:** All four Phase 2b resolution paths (A/B/C/C-lite) referenced; C-lite chosen; implementation covers CLI parity, hook behavior, CLAUDE.md non-mutation, docs, end-to-end verification.
- **Placeholder scan:** No TBDs, no "implement appropriate X", no "similar to Task N". Every code block is complete.
- **Type consistency:** `InitResult` used in `init.py`, imported into `cli.py` and `hooks.py`. Field names (`project_name`, `events_seeded`, `already_initialized`) consistent across all three files.
- **Test consistency:** `tests/test_init.py` imports `InitResult` and `perform_init`. `tests/test_hooks.py` does not import `perform_init` directly — it tests behavior through `handle_session_start`, which is the correct level of abstraction.
- **Edge case — dir without DB:** `perform_init` keys on `db_path.exists()` not `engram_dir.exists()`, so a stray `.engram/` without a DB triggers a full init. `mkdir(parents=True, exist_ok=True)` handles the already-present dir safely.
- **Edge case — concurrent hook invocation:** Two Claude Code sessions launching in the same uninit'd project both call `perform_init`. `mkdir(exist_ok=True)` plus the `db_path.exists()` guard means one succeeds and seeds; the other sees the DB mid-creation → races. If this becomes an issue, add a lockfile; deferred for now since simultaneous first-launches in one dir are rare.
- **Scope discipline:** No changes to `GitBootstrapper`, `EventStore`, MCP server, or plugin `hooks.json` — they are already correct for this behavior.
