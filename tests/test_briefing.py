"""Tests for the briefing generator."""

from engram.briefing import BriefingGenerator
from engram.formatting import format_briefing_compact, format_briefing_json
from engram.models import Event, EventType
import json


class TestBriefingGenerator:

    def test_generate_basic(self, seeded_store):
        seeded_store.set_meta("project_name", "test-project")
        gen = BriefingGenerator(seeded_store)
        briefing = gen.generate()

        assert briefing.project_name == "test-project"
        assert briefing.total_events == 8
        # All warnings should appear (2 in seeded_store, both have scope so they go to other_active)
        # Warnings with no scope go to critical, scoped warnings go to other_active
        total_warnings = sum(
            1 for e in briefing.critical_warnings + briefing.other_active
            if e.event_type == EventType.WARNING
        )
        assert total_warnings == 2
        assert len(briefing.recent_mutations) == 2

    def test_generate_with_scope(self, seeded_store):
        seeded_store.set_meta("project_name", "test-project")
        gen = BriefingGenerator(seeded_store)
        briefing = gen.generate(scope="src/auth")

        assert len(briefing.recent_mutations) == 1
        assert "JWT" in briefing.recent_mutations[0].content

    def test_generate_compact_output(self, seeded_store):
        seeded_store.set_meta("project_name", "test-project")
        gen = BriefingGenerator(seeded_store)
        briefing = gen.generate()
        output = format_briefing_compact(briefing)

        assert "# Engram Briefing — test-project" in output
        assert "Don't modify user_sessions" in output

    def test_generate_json_output(self, seeded_store):
        seeded_store.set_meta("project_name", "test-project")
        gen = BriefingGenerator(seeded_store)
        briefing = gen.generate()
        output = format_briefing_json(briefing)
        data = json.loads(output)

        assert data["project_name"] == "test-project"
        assert data["total_events"] == 8

    def test_generate_empty_store(self, store):
        store.set_meta("project_name", "empty-project")
        gen = BriefingGenerator(store)
        briefing = gen.generate()

        assert briefing.total_events == 0
        assert len(briefing.critical_warnings) == 0
        assert len(briefing.other_active) == 0
        assert len(briefing.recent_mutations) == 0

    def test_staleness_detection(self, store):
        """Warning with scope that was later mutated should be flagged stale."""
        store.set_meta("project_name", "stale-test")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.WARNING, agent_id="a",
                  content="Don't touch auth", scope=["src/auth.py"]),
            Event(id="", timestamp="2026-02-23T11:00:00+00:00",
                  event_type=EventType.MUTATION, agent_id="b",
                  content="Modified auth module", scope=["src/auth.py"]),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate()
        assert len(briefing.potentially_stale) == 1
        assert "auth" in briefing.potentially_stale[0].content

    def test_staleness_not_triggered_for_different_scope(self, store):
        """Warning and mutation with different scopes should not be flagged."""
        store.set_meta("project_name", "stale-test-2")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.WARNING, agent_id="a",
                  content="Don't touch auth", scope=["src/auth.py"]),
            Event(id="", timestamp="2026-02-23T11:00:00+00:00",
                  event_type=EventType.MUTATION, agent_id="b",
                  content="Modified database", scope=["src/db.py"]),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate()
        assert len(briefing.potentially_stale) == 0

    def test_deduplication_collapses_rapid_mutations(self, store):
        """Multiple mutations to same file within 30 min should collapse."""
        store.set_meta("project_name", "dedup-test")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.MUTATION, agent_id="a",
                  content="Edit 1", scope=["src/foo.py"]),
            Event(id="", timestamp="2026-02-23T10:05:00+00:00",
                  event_type=EventType.MUTATION, agent_id="a",
                  content="Edit 2", scope=["src/foo.py"]),
            Event(id="", timestamp="2026-02-23T10:10:00+00:00",
                  event_type=EventType.MUTATION, agent_id="a",
                  content="Edit 3", scope=["src/foo.py"]),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate()
        # 3 edits collapsed into 1
        assert len(briefing.recent_mutations) == 1
        assert "3 edits" in briefing.recent_mutations[0].content

    def test_deduplication_preserves_separate_files(self, store):
        """Mutations to different files should not be collapsed."""
        store.set_meta("project_name", "dedup-test-2")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.MUTATION, agent_id="a",
                  content="Edit foo", scope=["src/foo.py"]),
            Event(id="", timestamp="2026-02-23T10:05:00+00:00",
                  event_type=EventType.MUTATION, agent_id="a",
                  content="Edit bar", scope=["src/bar.py"]),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate()
        assert len(briefing.recent_mutations) == 2

    def test_deduplication_window_boundary(self, store):
        """Mutations with >30 min gap between consecutive edits should split."""
        store.set_meta("project_name", "window-test")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.MUTATION, agent_id="a",
                  content="Edit 1", scope=["src/foo.py"]),
            Event(id="", timestamp="2026-02-23T10:10:00+00:00",
                  event_type=EventType.MUTATION, agent_id="a",
                  content="Edit 2", scope=["src/foo.py"]),
            # 51 min gap from Edit 2 — new window (>30 min from previous)
            Event(id="", timestamp="2026-02-23T11:01:00+00:00",
                  event_type=EventType.MUTATION, agent_id="a",
                  content="Edit 3", scope=["src/foo.py"]),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate()
        # First two in one window (collapsed), third alone
        assert len(briefing.recent_mutations) == 2
        # Verify the collapsed entry mentions "2 edits"
        collapsed = [e for e in briefing.recent_mutations if "2 edits" in e.content]
        assert len(collapsed) == 1

    def test_deduplication_different_agents_not_collapsed(self, store):
        """Mutations from different agents to the same file should not collapse."""
        store.set_meta("project_name", "agent-dedup-test")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.MUTATION, agent_id="agent-a",
                  content="Agent A edit", scope=["src/foo.py"]),
            Event(id="", timestamp="2026-02-23T10:05:00+00:00",
                  event_type=EventType.MUTATION, agent_id="agent-b",
                  content="Agent B edit", scope=["src/foo.py"]),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate()
        assert len(briefing.recent_mutations) == 2

    def test_staleness_scopeless_warning_not_flagged(self, store):
        """A warning without scope should never be flagged stale."""
        store.set_meta("project_name", "scopeless-test")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.WARNING, agent_id="a",
                  content="General warning with no scope"),
            Event(id="", timestamp="2026-02-23T11:00:00+00:00",
                  event_type=EventType.MUTATION, agent_id="b",
                  content="Modified something", scope=["src/anything.py"]),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate()
        assert len(briefing.potentially_stale) == 0

    def test_staleness_shows_in_compact_output(self, store):
        """Stale events should appear in compact briefing output."""
        store.set_meta("project_name", "stale-output")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.DECISION, agent_id="a",
                  content="Use bcrypt", scope=["src/auth.py"]),
            Event(id="", timestamp="2026-02-23T11:00:00+00:00",
                  event_type=EventType.MUTATION, agent_id="b",
                  content="Rewrote auth", scope=["src/auth.py"]),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate()
        output = format_briefing_compact(briefing)
        assert "POSSIBLY STALE" in output
        assert "bcrypt" in output


class TestFocusBriefing:
    """Tests for scope-aware briefing with --focus."""

    def test_focus_moves_matching_events(self, store):
        """Events matching focus path should appear in focus_relevant."""
        store.set_meta("project_name", "focus-test")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.WARNING, agent_id="a",
                  content="Auth warning", scope=["src/auth/login.py"]),
            Event(id="", timestamp="2026-02-23T10:05:00+00:00",
                  event_type=EventType.DECISION, agent_id="a",
                  content="DB decision", scope=["src/db/pool.py"]),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate(focus="src/auth")

        focus_content = [e.content for e in briefing.focus_relevant]
        other_content = [e.content for e in briefing.other_active]
        assert "Auth warning" in focus_content
        assert "DB decision" in other_content

    def test_critical_warnings_bypass_focus(self, store):
        """Critical warnings always go to critical_warnings, not focus_relevant."""
        store.set_meta("project_name", "critical-test")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.WARNING, agent_id="a",
                  content="Critical auth issue", scope=["src/auth/login.py"],
                  priority="critical"),
            Event(id="", timestamp="2026-02-23T10:05:00+00:00",
                  event_type=EventType.WARNING, agent_id="a",
                  content="Normal auth warning", scope=["src/auth/login.py"]),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate(focus="src/auth")

        critical_content = [e.content for e in briefing.critical_warnings]
        focus_content = [e.content for e in briefing.focus_relevant]
        assert "Critical auth issue" in critical_content
        assert "Normal auth warning" in focus_content

    def test_global_warnings_in_critical(self, store):
        """Warnings with no scope go to critical_warnings."""
        store.set_meta("project_name", "global-test")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.WARNING, agent_id="a",
                  content="Global warning"),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate()

        critical_content = [e.content for e in briefing.critical_warnings]
        assert "Global warning" in critical_content

    def test_no_focus_everything_in_other_active(self, store):
        """Without --focus, no events go to focus_relevant."""
        store.set_meta("project_name", "nofocus-test")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.DECISION, agent_id="a",
                  content="Some decision", scope=["src/foo.py"]),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate()  # no focus

        assert len(briefing.focus_relevant) == 0
        assert len(briefing.other_active) == 1


class TestPriorityBriefing:
    """Tests for priority sorting in briefings."""

    def test_priority_sorting(self, store):
        """Higher priority events should appear first within a section."""
        store.set_meta("project_name", "priority-test")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.DECISION, agent_id="a",
                  content="Low priority", scope=["src/foo.py"],
                  priority="low"),
            Event(id="", timestamp="2026-02-23T10:05:00+00:00",
                  event_type=EventType.DECISION, agent_id="a",
                  content="High priority", scope=["src/foo.py"],
                  priority="high"),
            Event(id="", timestamp="2026-02-23T10:10:00+00:00",
                  event_type=EventType.DECISION, agent_id="a",
                  content="Normal priority", scope=["src/foo.py"]),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate()

        contents = [e.content for e in briefing.other_active
                     if e.event_type == EventType.DECISION]
        assert contents[0] == "High priority"

    def test_priority_in_compact_output(self, store):
        """Priority tag should appear in compact output for non-normal events."""
        store.set_meta("project_name", "prio-output")
        events = [
            Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                  event_type=EventType.WARNING, agent_id="a",
                  content="Critical issue", priority="critical"),
        ]
        store.insert_batch(events)

        gen = BriefingGenerator(store)
        briefing = gen.generate()
        output = format_briefing_compact(briefing)
        assert "[CRITICAL]" in output


class TestResolvedWindow:
    """Tests for recently resolved events in briefings."""

    def test_resolved_events_appear_in_recently_resolved(self, store):
        """Resolved events within window should appear in recently_resolved."""
        store.set_meta("project_name", "resolved-test")
        event = Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                      event_type=EventType.WARNING, agent_id="a",
                      content="Fixed issue")
        result = store.insert(event)
        store.update_status(result.id, "resolved", resolved_reason="Fixed in PR #42")

        gen = BriefingGenerator(store)
        # Use a very large window to ensure our event is included
        briefing = gen.generate(resolved_window_hours=9999)

        resolved_content = [e.content for e in briefing.recently_resolved]
        assert "Fixed issue" in resolved_content

    def test_resolved_events_not_in_active_sections(self, store):
        """Resolved events should not appear in critical/focus/other sections."""
        store.set_meta("project_name", "resolved-test-2")
        event = Event(id="", timestamp="2026-02-23T10:00:00+00:00",
                      event_type=EventType.WARNING, agent_id="a",
                      content="Resolved warning")
        result = store.insert(event)
        store.update_status(result.id, "resolved", resolved_reason="Done")

        gen = BriefingGenerator(store)
        briefing = gen.generate(resolved_window_hours=9999)

        all_active = briefing.critical_warnings + briefing.focus_relevant + briefing.other_active
        active_content = [e.content for e in all_active]
        assert "Resolved warning" not in active_content
