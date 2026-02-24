"""Tests for the multi-model provider abstraction."""

import os
from unittest.mock import patch, MagicMock

import pytest

from engram.providers import (
    MODELS, ModelConfig, send_message,
    _send_openai, _send_google, _send_anthropic,
    _get_api_key,
)


class TestModelRegistry:

    def test_expected_models_exist(self):
        assert "gpt-4o" in MODELS
        assert "gemini-flash" in MODELS
        assert "claude-sonnet" in MODELS

    def test_model_configs_have_required_fields(self):
        for key, config in MODELS.items():
            assert config.provider in ("openai", "google", "anthropic")
            assert config.model_id
            assert config.env_key


class TestAPIKey:

    def test_missing_api_key_raises(self):
        config = ModelConfig("openai", "gpt-4o", "NONEXISTENT_KEY_12345")
        with pytest.raises(ValueError, match="NONEXISTENT_KEY_12345"):
            _get_api_key(config)

    def test_api_key_from_env(self):
        config = ModelConfig("openai", "gpt-4o", "TEST_OPENAI_KEY_XYZ")
        with patch.dict(os.environ, {"TEST_OPENAI_KEY_XYZ": "sk-test123"}):
            assert _get_api_key(config) == "sk-test123"


class TestSendMessage:

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError, match="Unknown model"):
            send_message("nonexistent-model", [{"role": "user", "content": "hi"}])

    @patch("engram.providers._DISPATCH")
    def test_dispatch_openai(self, mock_dispatch):
        mock_fn = MagicMock(return_value="OpenAI response")
        mock_dispatch.__getitem__ = MagicMock(return_value=mock_fn)
        result = send_message("gpt-4o", [{"role": "user", "content": "hi"}])
        assert result == "OpenAI response"

    @patch("engram.providers._DISPATCH")
    def test_dispatch_google(self, mock_dispatch):
        mock_fn = MagicMock(return_value="Google response")
        mock_dispatch.__getitem__ = MagicMock(return_value=mock_fn)
        result = send_message("gemini-flash", [{"role": "user", "content": "hi"}])
        assert result == "Google response"

    @patch("engram.providers._DISPATCH")
    def test_dispatch_anthropic(self, mock_dispatch):
        mock_fn = MagicMock(return_value="Anthropic response")
        mock_dispatch.__getitem__ = MagicMock(return_value=mock_fn)
        result = send_message("claude-sonnet", [{"role": "user", "content": "hi"}])
        assert result == "Anthropic response"


class TestOpenAIProvider:

    @patch("engram.providers._get_api_key", return_value="sk-test")
    def test_send_openai_basic(self, mock_key):
        with patch.dict("sys.modules", {"openai": MagicMock()}):
            import sys
            mock_openai = sys.modules["openai"]
            mock_client = MagicMock()
            mock_openai.OpenAI.return_value = mock_client
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "Hello from GPT"
            mock_client.chat.completions.create.return_value = mock_response

            config = MODELS["gpt-4o"]
            result = _send_openai(config, [{"role": "user", "content": "hi"}], None)
            assert result == "Hello from GPT"

    @patch("engram.providers._get_api_key", return_value="sk-test")
    def test_send_openai_with_system_prompt(self, mock_key):
        with patch.dict("sys.modules", {"openai": MagicMock()}):
            import sys
            mock_openai = sys.modules["openai"]
            mock_client = MagicMock()
            mock_openai.OpenAI.return_value = mock_client
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "response"
            mock_client.chat.completions.create.return_value = mock_response

            config = MODELS["gpt-4o"]
            _send_openai(config, [{"role": "user", "content": "hi"}], "You are helpful")

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["messages"][0] == {"role": "system", "content": "You are helpful"}
            assert call_kwargs["messages"][1] == {"role": "user", "content": "hi"}


class TestAnthropicProvider:

    @patch("engram.providers._get_api_key", return_value="ant-test")
    def test_send_anthropic_basic(self, mock_key):
        with patch.dict("sys.modules", {"httpx": MagicMock()}):
            import sys
            mock_httpx = sys.modules["httpx"]
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "content": [{"type": "text", "text": "Hello from Claude"}]
            }
            mock_response.raise_for_status = MagicMock()
            mock_httpx.post.return_value = mock_response

            config = MODELS["claude-sonnet"]
            result = _send_anthropic(config, [{"role": "user", "content": "hi"}], None)
            assert result == "Hello from Claude"

    @patch("engram.providers._get_api_key", return_value="ant-test")
    def test_send_anthropic_with_system(self, mock_key):
        with patch.dict("sys.modules", {"httpx": MagicMock()}):
            import sys
            mock_httpx = sys.modules["httpx"]
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "content": [{"type": "text", "text": "response"}]
            }
            mock_response.raise_for_status = MagicMock()
            mock_httpx.post.return_value = mock_response

            config = MODELS["claude-sonnet"]
            _send_anthropic(config, [{"role": "user", "content": "hi"}], "Be concise")

            call_kwargs = mock_httpx.post.call_args
            body = call_kwargs[1]["json"]
            assert body["system"] == "Be concise"


class TestGoogleProvider:

    @patch("engram.providers._get_api_key", return_value="goog-test")
    def test_send_google_basic(self, mock_key):
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Hello from Gemini"
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_genai.Client.return_value = mock_client

        with patch.dict("sys.modules", {"google.genai": mock_genai}):
            # Force re-resolution of `from google import genai`
            import google
            google.genai = mock_genai
            try:
                config = MODELS["gemini-flash"]
                result = _send_google(config, [{"role": "user", "content": "hi"}], None)
                assert result == "Hello from Gemini"
            finally:
                delattr(google, "genai")
