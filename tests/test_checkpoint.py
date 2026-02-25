"""Tests for context checkpoint save/restore integration."""

import pytest

from engram.checkpoint import CheckpointEngine, ENGRAM_START, ENGRAM_END
from engram.models import Checkpoint, Event, EventType


# --- Store checkpoint CRUD ---


class TestCheckpointStore:
    """Test checkpoint store methods on EventStore."""

    def test_save_checkpoint(self, store):
        chk = Checkpoint(
            id="", file_path="/tmp/context.md", agent_id="cli",
            created_at="", event_count_at_creation=0,
        )
        result = store.save_checkpoint(chk)
        assert result.id.startswith("chk-")
        assert result.created_at != ""
        assert result.file_path == "/tmp/context.md"
        assert result.event_count_at_creation >= 0

    def test_get_latest_checkpoint(self, store):
        chk = Checkpoint(
            id="", file_path="/tmp/ctx.md", agent_id="cli",
            created_at="", event_count_at_creation=0,
        )
        saved = store.save_checkpoint(chk)
        latest = store.get_latest_checkpoint()
        assert latest is not None
        assert latest.id == saved.id
        assert latest.file_path == saved.file_path

    def test_get_latest_checkpoint_none(self, store):
        assert store.get_latest_checkpoint() is None

    def test_get_checkpoint_by_id(self, store):
        chk = Checkpoint(
            id="", file_path="/tmp/ctx.md", agent_id="cli",
            created_at="", event_count_at_creation=0,
        )
        saved = store.save_checkpoint(chk)
        fetched = store.get_checkpoint(saved.id)
        assert fetched is not None
        assert fetched.file_path == saved.file_path
        assert fetched.agent_id == saved.agent_id

    def test_get_checkpoint_not_found(self, store):
        assert store.get_checkpoint("chk-nonexist") is None

    def test_latest_updates_on_new_checkpoint(self, store):
        chk1 = store.save_checkpoint(Checkpoint(
            id="", file_path="/tmp/first.md", agent_id="cli",
            created_at="", event_count_at_creation=0,
        ))
        chk2 = store.save_checkpoint(Checkpoint(
            id="", file_path="/tmp/second.md", agent_id="cli",
            created_at="", event_count_at_creation=0,
        ))
        latest = store.get_latest_checkpoint()
        assert latest.id == chk2.id
        assert latest.file_path == "/tmp/second.md"

    def test_save_preserves_enriched_sections(self, store):
        chk = Checkpoint(
            id="", file_path="/tmp/ctx.md", agent_id="cli",
            created_at="", event_count_at_creation=0,
            enriched_sections=["Key Design Decisions", "Known Issues"],
        )
        saved = store.save_checkpoint(chk)
        fetched = store.get_checkpoint(saved.id)
        assert fetched.enriched_sections == ["Key Design Decisions", "Known Issues"]

    def test_save_preserves_session_id(self, store):
        chk = Checkpoint(
            id="", file_path="/tmp/ctx.md", agent_id="cli",
            created_at="", event_count_at_creation=0,
            session_id="sess-abc12345",
        )
        saved = store.save_checkpoint(chk)
        fetched = store.get_checkpoint(saved.id)
        assert fetched.session_id == "sess-abc12345"

    def test_event_count_auto_populated(self, store):
        # Insert some events first
        store.insert(Event(
            id="", timestamp="", event_type=EventType.DECISION,
            agent_id="cli", content="Test decision",
        ))
        chk = Checkpoint(
            id="", file_path="/tmp/ctx.md", agent_id="cli",
            created_at="", event_count_at_creation=0,
        )
        saved = store.save_checkpoint(chk)
        assert saved.event_count_at_creation == 1


# --- Enrichment ---


class TestCheckpointEnrich:
    """Test context file enrichment."""

    def test_enrich_adds_decisions(self, store, tmp_path):
        store.insert(Event(
            id="", timestamp="", event_type=EventType.DECISION,
            agent_id="cli", content="Use SQLite over Postgres for simplicity",
        ))
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text(
            "# Context\n\n## Key Design Decisions\n\n"
            "1. Some existing decision\n\n## Other\n\nStuff\n"
        )

        engine = CheckpointEngine(store, project_dir=tmp_path)
        result = engine.save(str(ctx_file), agent_id="cli")

        assert result.enriched_sections is not None
        assert "Key Design Decisions" in result.enriched_sections
        content = ctx_file.read_text()
        assert ENGRAM_START in content
        assert "SQLite over Postgres" in content

    def test_enrich_adds_warnings_to_known_issues(self, store, tmp_path):
        store.insert(Event(
            id="", timestamp="", event_type=EventType.WARNING,
            agent_id="cli", content="Don't use global state in handlers",
        ))
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text(
            "# Context\n\n## Known Issues\n\n"
            "1. Old issue\n\n## Other\n\nStuff\n"
        )

        engine = CheckpointEngine(store, project_dir=tmp_path)
        result = engine.save(str(ctx_file), agent_id="cli")

        assert "Known Issues" in result.enriched_sections
        content = ctx_file.read_text()
        assert "Don't use global state" in content

    def test_enrich_skips_already_present(self, store, tmp_path):
        store.insert(Event(
            id="", timestamp="", event_type=EventType.DECISION,
            agent_id="cli", content="Use SQLite over Postgres for simplicity",
        ))
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text(
            "# Context\n\n## Key Design Decisions\n\n"
            "Use SQLite over Postgres for simplicity\n\n## Other\n"
        )

        engine = CheckpointEngine(store, project_dir=tmp_path)
        result = engine.save(str(ctx_file), agent_id="cli")

        # Should not enrich because the content is already there
        assert result.enriched_sections is None

    def test_no_enrich_flag(self, store, tmp_path):
        store.insert(Event(
            id="", timestamp="", event_type=EventType.DECISION,
            agent_id="cli", content="Some decision not in file",
        ))
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("## Key Design Decisions\n\nOld stuff\n")

        engine = CheckpointEngine(store, project_dir=tmp_path)
        result = engine.save(str(ctx_file), agent_id="cli", enrich=False)

        assert result.enriched_sections is None
        assert ENGRAM_START not in ctx_file.read_text()

    def test_enrich_replaces_previous_enrichment(self, store, tmp_path):
        store.insert(Event(
            id="", timestamp="", event_type=EventType.WARNING,
            agent_id="cli", content="Don't use global state in handlers",
        ))
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text(
            "## Known Issues\n\nExisting issue\n"
            f"{ENGRAM_START}\nOld enrichment\n{ENGRAM_END}\n\n## Other\n"
        )

        engine = CheckpointEngine(store, project_dir=tmp_path)
        result = engine.save(str(ctx_file), agent_id="cli")

        content = ctx_file.read_text()
        assert content.count(ENGRAM_START) == 1  # replaced, not duplicated
        assert "Don't use global state" in content
        assert "Old enrichment" not in content

    def test_enrich_no_matching_sections(self, store, tmp_path):
        store.insert(Event(
            id="", timestamp="", event_type=EventType.DECISION,
            agent_id="cli", content="Some decision",
        ))
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("# Context\n\n## Architecture\n\nModule list\n")

        engine = CheckpointEngine(store, project_dir=tmp_path)
        result = engine.save(str(ctx_file), agent_id="cli")

        assert result.enriched_sections is None

    def test_enrich_no_events(self, store, tmp_path):
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("## Key Design Decisions\n\nSome stuff\n")

        engine = CheckpointEngine(store, project_dir=tmp_path)
        result = engine.save(str(ctx_file), agent_id="cli")

        assert result.enriched_sections is None


# --- Restore ---


class TestCheckpointRestore:
    """Test restore / full briefing."""

    def test_restore_with_checkpoint(self, store, tmp_path):
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("# My Context\n\nSome static content.\n")

        engine = CheckpointEngine(store, project_dir=tmp_path)
        chk = engine.save(str(ctx_file), agent_id="cli", enrich=False)

        output = engine.restore()
        assert "Saved Context" in output
        assert chk.id in output
        assert "Some static content" in output
        assert "Activity Since Checkpoint" in output

    def test_restore_no_checkpoint(self, store, tmp_path):
        engine = CheckpointEngine(store, project_dir=tmp_path)
        output = engine.restore()
        assert "No checkpoint found" in output
        assert "full dynamic briefing" in output

    def test_restore_missing_file(self, store, tmp_path):
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("Content\n")
        engine = CheckpointEngine(store, project_dir=tmp_path)
        engine.save(str(ctx_file), agent_id="cli", enrich=False)
        ctx_file.unlink()

        output = engine.restore()
        assert "not found" in output

    def test_restore_by_id(self, store, tmp_path):
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("# First checkpoint\n")
        engine = CheckpointEngine(store, project_dir=tmp_path)
        chk1 = engine.save(str(ctx_file), agent_id="cli", enrich=False)

        ctx_file.write_text("# Second checkpoint\n")
        chk2 = engine.save(str(ctx_file), agent_id="cli", enrich=False)

        # Restore by specific ID should use that checkpoint's timestamp
        output = engine.restore(checkpoint_id=chk1.id)
        assert chk1.id in output

    def test_restore_includes_recent_events(self, store, tmp_path):
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("# Context\n")
        engine = CheckpointEngine(store, project_dir=tmp_path)
        engine.save(str(ctx_file), agent_id="cli", enrich=False)

        # Post an event after checkpoint
        store.insert(Event(
            id="", timestamp="", event_type=EventType.DECISION,
            agent_id="cli", content="Post-checkpoint decision about caching",
        ))

        output = engine.restore()
        assert "Activity Since Checkpoint" in output

    def test_file_not_found_raises(self, store, tmp_path):
        engine = CheckpointEngine(store, project_dir=tmp_path)
        with pytest.raises(ValueError, match="not found"):
            engine.save("/nonexistent/file.md", agent_id="cli")
