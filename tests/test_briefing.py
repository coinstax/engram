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
        assert len(briefing.active_warnings) == 2
        assert len(briefing.recent_decisions) == 1
        assert len(briefing.recent_mutations) == 2
        assert len(briefing.recent_discoveries) == 2
        assert len(briefing.recent_outcomes) == 1

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
        assert "## Warnings (2)" in output
        assert "Don't modify user_sessions" in output

    def test_generate_json_output(self, seeded_store):
        seeded_store.set_meta("project_name", "test-project")
        gen = BriefingGenerator(seeded_store)
        briefing = gen.generate()
        output = format_briefing_json(briefing)
        data = json.loads(output)

        assert data["project_name"] == "test-project"
        assert data["total_events"] == 8
        assert len(data["active_warnings"]) == 2

    def test_generate_empty_store(self, store):
        store.set_meta("project_name", "empty-project")
        gen = BriefingGenerator(store)
        briefing = gen.generate()

        assert briefing.total_events == 0
        assert len(briefing.active_warnings) == 0
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
