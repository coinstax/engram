"""Tests for the briefing generator."""

from engram.briefing import BriefingGenerator
from engram.formatting import format_briefing_compact, format_briefing_json
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
