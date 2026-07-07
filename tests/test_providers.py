"""Tests for the multi-model provider abstraction."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from engram.providers import (
    MODELS, BUILTIN_MODELS, ModelConfig, send_message,
    _send_openai, _send_google, _send_anthropic,
    _get_api_key, load_model_overrides, resolve_models, model_summary,
)


class TestModelRegistry:

    def test_current_frontier_keys_exist(self):
        assert "gpt" in MODELS
        assert "claude-opus" in MODELS
        assert "claude-sonnet" in MODELS
        assert "gemini-pro" in MODELS
        assert "gemini-flash" in MODELS
        assert "grok" in MODELS

    def test_deprecated_aliases_still_resolve(self):
        # Old keys kept so stored conversations / muscle memory keep working.
        assert "gpt-4o" in MODELS
        assert "o3" in MODELS

    def test_models_point_at_current_ids(self):
        assert MODELS["claude-opus"].model_id == "claude-opus-4-8"
        assert MODELS["claude-sonnet"].model_id == "claude-sonnet-5"
        assert MODELS["gpt"].model_id == "gpt-5.5"
        assert MODELS["gemini-pro"].model_id == "gemini-3.1-pro-preview"
        assert MODELS["grok"].model_id == "grok-4.3"

    def test_grok_uses_openai_provider_with_custom_base_url(self):
        config = MODELS["grok"]
        assert config.provider == "openai"
        assert config.base_url == "https://api.x.ai/v1"
        assert config.env_key == "XAI_API_KEY"

    def test_model_configs_have_required_fields(self):
        for key, config in MODELS.items():
            assert config.provider in ("openai", "google", "anthropic")
            assert config.model_id
            assert config.env_key


class TestModelOverrides:

    def _write(self, tmp_path, payload):
        engram_dir = tmp_path / ".engram"
        engram_dir.mkdir(parents=True, exist_ok=True)
        (engram_dir / "models.json").write_text(json.dumps(payload))

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_model_overrides(tmp_path) == {}

    def test_malformed_json_returns_empty(self, tmp_path):
        engram_dir = tmp_path / ".engram"
        engram_dir.mkdir(parents=True)
        (engram_dir / "models.json").write_text("{ not json")
        assert load_model_overrides(tmp_path) == {}

    def test_valid_override_loads(self, tmp_path):
        self._write(tmp_path, {"models": {
            "my-gpt": {
                "provider": "openai", "model_id": "gpt-5.5-mini",
                "env_key": "OPENAI_API_KEY", "reasoning_effort": "medium",
            }
        }})
        overrides = load_model_overrides(tmp_path)
        assert "my-gpt" in overrides
        assert overrides["my-gpt"].model_id == "gpt-5.5-mini"
        assert overrides["my-gpt"].reasoning_effort == "medium"

    def test_invalid_entries_skipped(self, tmp_path):
        self._write(tmp_path, {"models": {
            "good": {"provider": "openai", "model_id": "x", "env_key": "K"},
            "bad-provider": {"provider": "cohere", "model_id": "y", "env_key": "K"},
            "missing-id": {"provider": "openai", "env_key": "K"},
        }})
        overrides = load_model_overrides(tmp_path)
        assert "good" in overrides
        assert "bad-provider" not in overrides
        assert "missing-id" not in overrides

    def test_resolve_merges_and_overrides_win(self, tmp_path):
        self._write(tmp_path, {"models": {
            "gpt": {"provider": "openai", "model_id": "custom-gpt", "env_key": "OPENAI_API_KEY"},
            "local": {"provider": "openai", "model_id": "llama", "env_key": "LOCAL_KEY"},
        }})
        merged = resolve_models(tmp_path)
        assert merged["gpt"].model_id == "custom-gpt"   # override wins
        assert "local" in merged                         # custom added
        assert merged["claude-opus"].model_id == "claude-opus-4-8"  # builtin intact

    def test_model_summary_loads_dotenv_before_checking_keys(self, tmp_path):
        # Regression: key_present must reflect .env (what consult actually
        # loads), not just the raw process environment.
        def fake_load_env():
            os.environ["FAKE_DOTENV_KEY"] = "from-dotenv"

        custom = {"local": ModelConfig("openai", "llama", "FAKE_DOTENV_KEY")}
        with patch("engram.providers._load_env", side_effect=fake_load_env):
            try:
                rows = {r["key"]: r for r in model_summary(custom)}
            finally:
                os.environ.pop("FAKE_DOTENV_KEY", None)
        assert rows["local"]["key_present"] is True

    def test_model_summary_marks_source_and_key_presence(self, tmp_path):
        self._write(tmp_path, {"models": {
            "local": {"provider": "openai", "model_id": "llama", "env_key": "LOCAL_KEY_XYZ"},
        }})
        with patch.dict(os.environ, {"LOCAL_KEY_XYZ": "secret"}, clear=False):
            rows = {r["key"]: r for r in model_summary(resolve_models(tmp_path))}
        assert rows["local"]["source"] == "custom"
        assert rows["local"]["key_present"] is True
        assert rows["gpt"]["source"] == "builtin"


class TestAPIKey:

    def test_missing_api_key_raises(self):
        config = ModelConfig("openai", "gpt-5.5", "NONEXISTENT_KEY_12345")
        with pytest.raises(ValueError, match="NONEXISTENT_KEY_12345"):
            _get_api_key(config)

    def test_api_key_from_env(self):
        config = ModelConfig("openai", "gpt-5.5", "TEST_OPENAI_KEY_XYZ")
        with patch.dict(os.environ, {"TEST_OPENAI_KEY_XYZ": "sk-test123"}):
            assert _get_api_key(config) == "sk-test123"


class TestSendMessage:

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError, match="Unknown model"):
            send_message("nonexistent-model", [{"role": "user", "content": "hi"}])

    def test_custom_models_map_honored(self):
        custom = {"local": ModelConfig("openai", "llama", "LOCAL_KEY")}
        with patch("engram.providers._DISPATCH") as mock_dispatch:
            mock_fn = MagicMock(return_value="local response")
            mock_dispatch.__getitem__ = MagicMock(return_value=mock_fn)
            result = send_message("local", [{"role": "user", "content": "hi"}], models=custom)
        assert result == "local response"

    @patch("engram.providers._DISPATCH")
    def test_dispatch_openai(self, mock_dispatch):
        mock_fn = MagicMock(return_value="OpenAI response")
        mock_dispatch.__getitem__ = MagicMock(return_value=mock_fn)
        result = send_message("gpt", [{"role": "user", "content": "hi"}])
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


class TestMissingSDK:

    def _hide(self, name):
        import sys
        saved = {m: sys.modules.get(m) for m in list(sys.modules) if m == name or m.startswith(name + ".")}
        for m in saved:
            del sys.modules[m]
        sys.modules[name] = None  # forces ImportError on `from name import ...`
        return saved

    def _restore(self, name, saved):
        import sys
        sys.modules.pop(name, None)
        sys.modules.update({k: v for k, v in saved.items() if v is not None})

    @patch("engram.providers._get_api_key", return_value="sk-test")
    def test_missing_openai_sdk_gives_install_hint(self, mock_key):
        saved = self._hide("openai")
        try:
            with pytest.raises(ImportError, match=r"engram\[consult\]"):
                _send_openai(MODELS["gpt"], [{"role": "user", "content": "hi"}], None)
        finally:
            self._restore("openai", saved)

    @patch("engram.providers._get_api_key", return_value="ant-test")
    def test_missing_httpx_gives_install_hint(self, mock_key):
        saved = self._hide("httpx")
        try:
            with pytest.raises(ImportError, match=r"engram\[consult\]"):
                _send_anthropic(MODELS["claude-opus"], [{"role": "user", "content": "hi"}], None)
        finally:
            self._restore("httpx", saved)


class TestOpenAIProvider:

    def _mock_openai(self, content="response"):
        import sys
        mock_openai = sys.modules["openai"]
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = content
        mock_client.chat.completions.create.return_value = mock_response
        return mock_client

    @patch("engram.providers._get_api_key", return_value="sk-test")
    def test_send_openai_basic(self, mock_key):
        with patch.dict("sys.modules", {"openai": MagicMock()}):
            self._mock_openai("Hello from GPT")
            result = _send_openai(MODELS["gpt"], [{"role": "user", "content": "hi"}], None)
            assert result == "Hello from GPT"

    @patch("engram.providers._get_api_key", return_value="sk-test")
    def test_reasoning_model_uses_developer_role_and_effort(self, mock_key):
        with patch.dict("sys.modules", {"openai": MagicMock()}):
            client = self._mock_openai()
            _send_openai(MODELS["gpt"], [{"role": "user", "content": "hi"}], "You are helpful")
            call_kwargs = client.chat.completions.create.call_args[1]
            assert call_kwargs["messages"][0] == {"role": "developer", "content": "You are helpful"}
            assert call_kwargs["reasoning_effort"] == "high"

    @patch("engram.providers._get_api_key", return_value="sk-test")
    def test_non_reasoning_model_uses_system_role_no_effort(self, mock_key):
        with patch.dict("sys.modules", {"openai": MagicMock()}):
            client = self._mock_openai()
            # grok has no reasoning_effort → plain system role, no effort param.
            _send_openai(MODELS["grok"], [{"role": "user", "content": "hi"}], "Be helpful")
            call_kwargs = client.chat.completions.create.call_args[1]
            assert call_kwargs["messages"][0] == {"role": "system", "content": "Be helpful"}
            assert "reasoning_effort" not in call_kwargs


class TestAnthropicProvider:

    def _mock_httpx(self, text="response"):
        import sys
        mock_httpx = sys.modules["httpx"]
        mock_response = MagicMock()
        mock_response.json.return_value = {"content": [{"type": "text", "text": text}]}
        mock_response.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_response
        return mock_httpx

    @patch("engram.providers._get_api_key", return_value="ant-test")
    def test_send_anthropic_basic(self, mock_key):
        with patch.dict("sys.modules", {"httpx": MagicMock()}):
            self._mock_httpx("Hello from Claude")
            result = _send_anthropic(MODELS["claude-sonnet"], [{"role": "user", "content": "hi"}], None)
            assert result == "Hello from Claude"

    @patch("engram.providers._get_api_key", return_value="ant-test")
    def test_send_anthropic_with_system(self, mock_key):
        with patch.dict("sys.modules", {"httpx": MagicMock()}):
            mock_httpx = self._mock_httpx()
            _send_anthropic(MODELS["claude-sonnet"], [{"role": "user", "content": "hi"}], "Be concise")
            body = mock_httpx.post.call_args[1]["json"]
            assert body["system"] == "Be concise"

    @patch("engram.providers._get_api_key", return_value="ant-test")
    def test_thinking_model_uses_adaptive_not_budget_tokens(self, mock_key):
        # Regression: budget_tokens is a 400 on Opus 4.8 / Sonnet 5.
        with patch.dict("sys.modules", {"httpx": MagicMock()}):
            mock_httpx = self._mock_httpx()
            _send_anthropic(MODELS["claude-opus"], [{"role": "user", "content": "hi"}], None)
            body = mock_httpx.post.call_args[1]["json"]
            assert body["thinking"] == {"type": "adaptive"}
            assert "budget_tokens" not in body["thinking"]


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
