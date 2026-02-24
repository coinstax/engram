"""Tests for the ConsultationEngine."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from engram.models import Event, EventType
from engram.store import EventStore
from engram.consult import ConsultationEngine


@pytest.fixture
def engine(tmp_path):
    """Create an initialized store + engine for testing."""
    db_path = tmp_path / ".engram" / "events.db"
    db_path.parent.mkdir(parents=True)
    store = EventStore(db_path)
    store.initialize()
    store.set_meta("schema_version", "3")
    store.set_meta("project_name", "test-project")
    yield ConsultationEngine(store, project_dir=tmp_path)
    store.close()


class TestStart:

    def test_start_creates_conversation(self, engine):
        conv_id = engine.start("Test topic", ["gpt-4o"])
        assert conv_id.startswith("conv-")

        conv = engine.get_conversation(conv_id)
        assert conv["topic"] == "Test topic"
        assert conv["status"] == "active"
        assert conv["models"] == ["gpt-4o"]
        assert conv["messages"] == []

    def test_start_with_system_prompt(self, engine):
        conv_id = engine.start("Test", ["gpt-4o"], system_prompt="Be concise")
        conv = engine.get_conversation(conv_id)
        assert conv["system_prompt"] == "Be concise"

    def test_start_multiple_models(self, engine):
        conv_id = engine.start("Test", ["gpt-4o", "gemini-flash"])
        conv = engine.get_conversation(conv_id)
        assert conv["models"] == ["gpt-4o", "gemini-flash"]

    def test_start_unknown_model_raises(self, engine):
        with pytest.raises(ValueError, match="Unknown model"):
            engine.start("Test", ["nonexistent-model"])


class TestAddMessage:

    def test_add_message_stores_correctly(self, engine):
        conv_id = engine.start("Test", ["gpt-4o"])
        msg = engine.add_message(conv_id, "What about X?")

        assert msg["role"] == "user"
        assert msg["sender"] == "host"
        assert msg["content"] == "What about X?"

        conv = engine.get_conversation(conv_id)
        assert len(conv["messages"]) == 1
        assert conv["messages"][0]["content"] == "What about X?"

    def test_add_message_to_completed_raises(self, engine):
        conv_id = engine.start("Test", ["gpt-4o"])
        engine.complete(conv_id)
        with pytest.raises(ValueError, match="completed"):
            engine.add_message(conv_id, "too late")

    def test_add_message_nonexistent_raises(self, engine):
        with pytest.raises(ValueError, match="not found"):
            engine.add_message("conv-nonexistent", "hello")


class TestGetResponses:

    @patch("engram.consult.providers.send_message")
    def test_get_responses_calls_providers(self, mock_send, engine):
        mock_send.return_value = "I think X is better"
        conv_id = engine.start("Test", ["gpt-4o"])
        engine.add_message(conv_id, "What do you think?")

        responses = engine.get_responses(conv_id)

        assert len(responses) == 1
        assert responses[0]["sender"] == "gpt-4o"
        assert responses[0]["content"] == "I think X is better"
        assert responses[0]["role"] == "assistant"
        mock_send.assert_called_once()

    @patch("engram.consult.providers.send_message")
    def test_get_responses_multi_model(self, mock_send, engine):
        mock_send.side_effect = ["GPT says yes", "Gemini says no"]
        conv_id = engine.start("Test", ["gpt-4o", "gemini-flash"])
        engine.add_message(conv_id, "Should we?")

        responses = engine.get_responses(conv_id)

        assert len(responses) == 2
        assert responses[0]["sender"] == "gpt-4o"
        assert responses[0]["content"] == "GPT says yes"
        assert responses[1]["sender"] == "gemini-flash"
        assert responses[1]["content"] == "Gemini says no"

    @patch("engram.consult.providers.send_message")
    def test_get_responses_saves_to_db(self, mock_send, engine):
        mock_send.return_value = "Response text"
        conv_id = engine.start("Test", ["gpt-4o"])
        engine.add_message(conv_id, "Question")
        engine.get_responses(conv_id)

        conv = engine.get_conversation(conv_id)
        assert len(conv["messages"]) == 2
        assert conv["messages"][1]["sender"] == "gpt-4o"

    @patch("engram.consult.providers.send_message")
    def test_get_responses_handles_api_error(self, mock_send, engine):
        mock_send.side_effect = Exception("API timeout")
        conv_id = engine.start("Test", ["gpt-4o"])
        engine.add_message(conv_id, "Question")

        responses = engine.get_responses(conv_id)
        assert "[Error from gpt-4o:" in responses[0]["content"]

    @patch("engram.consult.providers.send_message")
    def test_get_responses_completed_raises(self, mock_send, engine):
        mock_send.return_value = "Response"
        conv_id = engine.start("Test", ["gpt-4o"])
        engine.add_message(conv_id, "Q")
        engine.get_responses(conv_id)
        engine.complete(conv_id)
        with pytest.raises(ValueError, match="completed"):
            engine.get_responses(conv_id)


class TestMessageHistoryFormatting:

    @patch("engram.consult.providers.send_message")
    def test_multi_model_concatenation(self, mock_send, engine):
        """When multiple models respond, their responses should be concatenated
        with sender labels for the next API call."""
        # First round
        mock_send.side_effect = ["GPT response", "Gemini response", "GPT round 2"]
        conv_id = engine.start("Test", ["gpt-4o", "gemini-flash"])
        engine.add_message(conv_id, "Initial question")
        engine.get_responses(conv_id)

        # Second round - only ask GPT
        engine.add_message(conv_id, "Follow-up")
        engine.get_responses(conv_id, models=["gpt-4o"])

        # Check what was sent to GPT in round 2
        last_call = mock_send.call_args_list[-1]
        messages = last_call[0][1]  # second positional arg

        # Should have: user msg, assistant (concatenated), user follow-up
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Initial question"
        assert messages[1]["role"] == "assistant"
        assert "[gpt-4o]: GPT response" in messages[1]["content"]
        assert "[gemini-flash]: Gemini response" in messages[1]["content"]
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "Follow-up"


class TestTokenTruncation:

    @patch("engram.consult.providers.send_message")
    def test_truncation_with_long_history(self, mock_send, engine):
        mock_send.return_value = "ok"
        conv_id = engine.start("Test", ["gpt-4o"])

        # Add many long messages to exceed 80k chars
        for i in range(50):
            engine.add_message(conv_id, f"Message {i}: {'x' * 2000}")
            engine.get_responses(conv_id)

        # Next call should truncate
        engine.add_message(conv_id, "Final question")
        engine.get_responses(conv_id)

        last_call = mock_send.call_args_list[-1]
        messages = last_call[0][1]

        # Should have truncation marker
        has_truncation = any("truncated" in m["content"] for m in messages)
        assert has_truncation

        # First and last messages should be preserved
        assert messages[0]["content"].startswith("Message 0:")
        assert messages[-1]["content"] == "Final question"


class TestComplete:

    def test_complete_sets_status(self, engine):
        conv_id = engine.start("Test", ["gpt-4o"])
        result = engine.complete(conv_id)
        assert result["status"] == "completed"

    def test_complete_with_summary(self, engine):
        conv_id = engine.start("Test", ["gpt-4o"])
        result = engine.complete(conv_id, summary="We decided X")
        assert result["summary"] == "We decided X"


class TestExtractEvent:

    def test_extract_event_creates_linked_event(self, engine):
        conv_id = engine.start("Test", ["gpt-4o"])
        event_id = engine.extract_event(conv_id, "decision", "We decided to use SQLite")

        assert event_id.startswith("evt-")

        # Verify event was created with related_ids
        events = engine.store.query_related(conv_id)
        assert len(events) == 1
        assert events[0].content == "We decided to use SQLite"
        assert events[0].event_type == EventType.DECISION
        assert conv_id in events[0].related_ids

    def test_extract_event_nonexistent_conv_raises(self, engine):
        with pytest.raises(ValueError, match="not found"):
            engine.extract_event("conv-fake", "decision", "nope")


class TestListConversations:

    def test_list_empty(self, engine):
        result = engine.list_conversations()
        assert result == []

    def test_list_all(self, engine):
        engine.start("Topic A", ["gpt-4o"])
        engine.start("Topic B", ["gemini-flash"])
        result = engine.list_conversations()
        assert len(result) == 2

    def test_list_filter_by_status(self, engine):
        conv_a = engine.start("Topic A", ["gpt-4o"])
        engine.start("Topic B", ["gpt-4o"])
        engine.complete(conv_a)

        active = engine.list_conversations(status="active")
        assert len(active) == 1
        assert active[0]["topic"] == "Topic B"

        completed = engine.list_conversations(status="completed")
        assert len(completed) == 1
        assert completed[0]["topic"] == "Topic A"

    def test_list_includes_message_count(self, engine):
        conv_id = engine.start("Test", ["gpt-4o"])
        engine.add_message(conv_id, "hello")
        result = engine.list_conversations()
        assert result[0]["message_count"] == 1


class TestSaveLog:

    def test_log_file_created(self, engine, tmp_path):
        conv_id = engine.start("Test topic", ["gpt-4o"])
        log_path = tmp_path / "docs" / "consultations" / f"{conv_id}.md"
        assert log_path.exists()

    def test_log_contains_metadata(self, engine, tmp_path):
        conv_id = engine.start("Design review", ["gpt-4o", "gemini-flash"],
                               system_prompt="Be thorough")
        log_path = tmp_path / "docs" / "consultations" / f"{conv_id}.md"
        content = log_path.read_text()

        assert "# Consultation: Design review" in content
        assert f"- ID: {conv_id}" in content
        assert "gpt-4o, gemini-flash" in content
        assert "active" in content
        assert "## System Prompt" in content
        assert "Be thorough" in content

    @patch("engram.consult.providers.send_message")
    def test_log_contains_messages(self, mock_send, engine, tmp_path):
        mock_send.return_value = "Model response"
        conv_id = engine.start("Test", ["gpt-4o"])
        engine.add_message(conv_id, "My question")
        engine.get_responses(conv_id)

        log_path = tmp_path / "docs" / "consultations" / f"{conv_id}.md"
        content = log_path.read_text()

        assert "## Turn 1" in content
        assert "**host**" in content
        assert "My question" in content
        assert "**gpt-4o**" in content
        assert "Model response" in content

    @patch("engram.consult.providers.send_message")
    def test_log_updated_on_each_turn(self, mock_send, engine, tmp_path):
        mock_send.return_value = "Response"
        conv_id = engine.start("Test", ["gpt-4o"])

        engine.add_message(conv_id, "Question 1")
        engine.get_responses(conv_id)

        engine.add_message(conv_id, "Question 2")
        engine.get_responses(conv_id)

        log_path = tmp_path / "docs" / "consultations" / f"{conv_id}.md"
        content = log_path.read_text()

        assert "## Turn 1" in content
        assert "## Turn 2" in content
        assert "Question 1" in content
        assert "Question 2" in content

    def test_log_contains_summary_on_complete(self, engine, tmp_path):
        conv_id = engine.start("Test", ["gpt-4o"])
        engine.complete(conv_id, summary="Decided to use approach A")

        log_path = tmp_path / "docs" / "consultations" / f"{conv_id}.md"
        content = log_path.read_text()
        assert "## Summary" in content
        assert "Decided to use approach A" in content
