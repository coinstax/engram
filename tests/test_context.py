"""Tests for auto-context assembly."""

import pytest
from pathlib import Path

from engram.context import ContextAssembler, MAX_CONTEXT_CHARS


@pytest.fixture
def assembler(store, tmp_path):
    """ContextAssembler with empty store and tmp project dir."""
    store.set_meta("project_name", "test-project")
    return ContextAssembler(store, project_dir=tmp_path)


@pytest.fixture
def assembler_seeded(seeded_store, tmp_path):
    """ContextAssembler with seeded store and tmp project dir."""
    seeded_store.set_meta("project_name", "test-project")
    return ContextAssembler(seeded_store, project_dir=tmp_path)


class TestAssemble:
    def test_empty_store_produces_valid_context(self, assembler):
        result = assembler.assemble()
        assert "# Project: test-project" in result
        assert "Total events in memory: 0" in result

    def test_includes_topic_when_provided(self, assembler):
        result = assembler.assemble(topic="Should we use Redis?")
        assert "Should we use Redis?" in result
        assert "Consultation Topic" in result

    def test_no_topic_section_when_omitted(self, assembler):
        result = assembler.assemble()
        assert "Consultation Topic" not in result

    def test_includes_readme_when_present(self, assembler, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# My Project\n\nThis is a test project.\n")
        result = assembler.assemble()
        assert "My Project" in result
        assert "Project Overview (from README)" in result

    def test_no_crash_when_readme_missing(self, assembler):
        result = assembler.assemble()
        assert "Project Overview (from README)" not in result
        # Should still produce valid context
        assert "# Project:" in result

    def test_includes_warnings(self, assembler_seeded):
        result = assembler_seeded.assemble()
        assert "Active Warnings" in result
        assert "Don't modify user_sessions table" in result

    def test_includes_decisions(self, assembler_seeded):
        result = assembler_seeded.assemble()
        assert "Recent Decisions" in result
        assert "bcrypt" in result

    def test_includes_discoveries(self, assembler_seeded):
        result = assembler_seeded.assemble()
        assert "Recent Discoveries" in result
        assert "connection pool" in result

    def test_readme_truncation_for_long_readme(self, assembler, tmp_path):
        readme = tmp_path / "README.md"
        # Write a very long README
        lines = [f"Line {i}: " + "x" * 100 for i in range(200)]
        readme.write_text("\n".join(lines))
        result = assembler.assemble()
        assert len(result) <= MAX_CONTEXT_CHARS + 50  # small tolerance for truncation marker

    def test_source_modules_listed(self, assembler, tmp_path):
        src_dir = tmp_path / "src" / "engram"
        src_dir.mkdir(parents=True)
        (src_dir / "store.py").write_text("")
        (src_dir / "cli.py").write_text("")
        (src_dir / "context.py").write_text("")

        result = assembler.assemble()
        assert "Source Modules" in result
        assert "store.py" in result
        assert "cli.py" in result

    def test_no_source_modules_when_dir_missing(self, assembler):
        result = assembler.assemble()
        assert "Source Modules" not in result


class TestAssembleForConsultation:
    def test_includes_role_framing(self, assembler):
        result = assembler.assemble_for_consultation(
            topic="Architecture review",
            models=["gpt-4o", "gemini-flash"],
        )
        assert "technical reviewer" in result
        assert "test-project" in result
        assert "gpt-4o, gemini-flash" in result

    def test_includes_context_after_framing(self, assembler_seeded):
        result = assembler_seeded.assemble_for_consultation(
            topic="P0 features",
            models=["gpt-4o"],
        )
        assert "---" in result  # separator between framing and context
        assert "Active Warnings" in result
        assert "P0 features" in result


class TestContextSummary:
    def test_summary_with_events(self, assembler_seeded, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# Test\n")
        result = assembler_seeded.context_summary()
        assert "README" in result
        assert "warnings" in result
        assert "decisions" in result

    def test_summary_empty_store_no_readme(self, assembler):
        result = assembler.context_summary()
        assert "minimal" in result

    def test_summary_with_readme_only(self, assembler, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# Test\n")
        result = assembler.context_summary()
        assert "README" in result
