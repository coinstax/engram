"""Multi-model provider abstraction for AI consultations."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ModelConfig:
    provider: str
    model_id: str
    env_key: str
    base_url: str | None = None
    thinking: bool = False


MODELS: dict[str, ModelConfig] = {
    # Standard models
    "gpt-4o": ModelConfig("openai", "gpt-4o", "OPENAI_API_KEY"),
    "gemini-flash": ModelConfig("google", "gemini-2.5-flash", "GOOGLE_API_KEY"),
    "claude-sonnet": ModelConfig("anthropic", "claude-sonnet-4-20250514", "ANTHROPIC_API_KEY"),
    "grok": ModelConfig("openai", "grok-3-latest", "XAI_API_KEY", base_url="https://api.x.ai/v1"),
    # Thinking models
    "o3": ModelConfig("openai", "o3", "OPENAI_API_KEY", thinking=True),
    "claude-opus": ModelConfig("anthropic", "claude-opus-4-20250514", "ANTHROPIC_API_KEY", thinking=True),
    "gemini-pro": ModelConfig("google", "gemini-2.5-pro", "GOOGLE_API_KEY", thinking=True),
}


def _load_env() -> None:
    """Load .env file from project root if python-dotenv is available."""
    try:
        from dotenv import load_dotenv
        # Walk up from CWD looking for .env
        cwd = Path.cwd()
        for parent in [cwd, *cwd.parents]:
            env_file = parent / ".env"
            if env_file.exists():
                load_dotenv(env_file)
                return
    except ImportError:
        pass


def _get_api_key(config: ModelConfig) -> str:
    """Get API key from environment, raising clear error if missing."""
    _load_env()
    key = os.environ.get(config.env_key)
    if not key:
        raise ValueError(
            f"API key not found: set {config.env_key} environment variable "
            f"or add it to a .env file."
        )
    return key


def _send_openai(config: ModelConfig, messages: list[dict], system_prompt: str | None) -> str:
    """Send via OpenAI SDK (also handles OpenAI-compatible APIs like xAI)."""
    from openai import OpenAI
    kwargs = {"api_key": _get_api_key(config)}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    client = OpenAI(**kwargs)

    api_messages = []
    if system_prompt:
        if config.thinking:
            # o3/reasoning models: use developer message instead of system
            api_messages.append({"role": "developer", "content": system_prompt})
        else:
            api_messages.append({"role": "system", "content": system_prompt})
    api_messages.extend(messages)

    create_kwargs: dict = {"model": config.model_id, "messages": api_messages}
    if config.thinking:
        create_kwargs["reasoning_effort"] = "high"

    response = client.chat.completions.create(**create_kwargs)
    return response.choices[0].message.content


def _send_google(config: ModelConfig, messages: list[dict], system_prompt: str | None) -> str:
    """Send via Google GenAI SDK (google-genai, not deprecated google-generativeai)."""
    from google import genai

    client = genai.Client(api_key=_get_api_key(config))

    # Convert to Google's content format
    contents = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(genai.types.Content(
            role=role,
            parts=[genai.types.Part(text=msg["content"])],
        ))

    config_kwargs: dict = {}
    if system_prompt:
        config_kwargs["system_instruction"] = system_prompt
    if config.thinking:
        config_kwargs["thinking_config"] = genai.types.ThinkingConfig(
            thinking_budget=10000,
        )
        config_kwargs["http_options"] = genai.types.HttpOptions(timeout=300_000)

    response = client.models.generate_content(
        model=config.model_id,
        contents=contents,
        config=genai.types.GenerateContentConfig(**config_kwargs) if config_kwargs else None,
    )
    return response.text


def _send_anthropic(config: ModelConfig, messages: list[dict], system_prompt: str | None) -> str:
    """Send via Anthropic API using httpx directly."""
    import httpx

    api_key = _get_api_key(config)

    body: dict = {
        "model": config.model_id,
        "max_tokens": 16384 if config.thinking else 4096,
        "messages": messages,
    }
    if system_prompt:
        body["system"] = system_prompt

    if config.thinking:
        body["thinking"] = {"type": "enabled", "budget_tokens": 10000}

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=body,
        timeout=300.0 if config.thinking else 120.0,
    )
    response.raise_for_status()
    data = response.json()
    # Extract text from content blocks (skip thinking blocks)
    return "".join(
        block["text"] for block in data["content"]
        if block["type"] == "text"
    )


_DISPATCH = {
    "openai": _send_openai,
    "google": _send_google,
    "anthropic": _send_anthropic,
}


def send_message(
    model_key: str,
    messages: list[dict],
    system_prompt: str | None = None,
) -> str:
    """Send conversation history to a model, return response text.

    Args:
        model_key: Key from MODELS dict (e.g., "gpt-4o", "gemini-flash", "claude-sonnet")
        messages: List of {"role": "user"|"assistant", "content": "..."} dicts
        system_prompt: Optional system/context prompt
    """
    if model_key not in MODELS:
        raise ValueError(f"Unknown model: {model_key}. Available: {list(MODELS.keys())}")

    config = MODELS[model_key]
    dispatch_fn = _DISPATCH[config.provider]
    return dispatch_fn(config, messages, system_prompt)
