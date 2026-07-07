"""Multi-model provider abstraction for AI consultations.

Model IDs are refreshed to current frontier flagships (mid-2026). The curated
set can be extended or overridden per project via .engram/models.json so the
list never goes fully stale — see load_model_overrides / resolve_models.
"""

import json
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
    # OpenAI-family reasoning effort ("low"|"medium"|"high"|"xhigh"); None = off.
    reasoning_effort: str | None = None


# Curated frontier flagships (verified current 2026). Keys are version-agnostic
# so refreshing a model_id below never renames the key users type.
BUILTIN_MODELS: dict[str, ModelConfig] = {
    "gpt": ModelConfig("openai", "gpt-5.5", "OPENAI_API_KEY", reasoning_effort="high"),
    "claude-opus": ModelConfig("anthropic", "claude-opus-4-8", "ANTHROPIC_API_KEY", thinking=True),
    "claude-sonnet": ModelConfig("anthropic", "claude-sonnet-5", "ANTHROPIC_API_KEY", thinking=True),
    "gemini-pro": ModelConfig("google", "gemini-3.1-pro-preview", "GOOGLE_API_KEY", thinking=True),
    "gemini-flash": ModelConfig("google", "gemini-3.5-flash", "GOOGLE_API_KEY"),
    "grok": ModelConfig("openai", "grok-4.3", "XAI_API_KEY", base_url="https://api.x.ai/v1"),
    # Deprecated aliases — kept so old keys / stored conversations still resolve.
    "gpt-4o": ModelConfig("openai", "gpt-5.5", "OPENAI_API_KEY", reasoning_effort="high"),
    "o3": ModelConfig("openai", "gpt-5.5", "OPENAI_API_KEY", reasoning_effort="high"),
}

# Back-compat module alias: existing callers import providers.MODELS directly.
MODELS = BUILTIN_MODELS

_VALID_PROVIDERS = ("openai", "google", "anthropic")


def load_model_overrides(project_dir: Path | str) -> dict[str, ModelConfig]:
    """Load extra/override models from <project_dir>/.engram/models.json.

    Shape: {"models": {"<key>": {"provider", "model_id", "env_key",
    "base_url"?, "thinking"?, "reasoning_effort"?}}}. Missing file,
    unreadable file, malformed JSON, or a bad entry are all best-effort
    non-fatal — invalid entries are skipped, the rest still load.
    """
    path = Path(project_dir) / ".engram" / "models.json"
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    raw = data.get("models") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}

    out: dict[str, ModelConfig] = {}
    for key, spec in raw.items():
        if not (isinstance(key, str) and isinstance(spec, dict)):
            continue
        provider = spec.get("provider")
        model_id = spec.get("model_id")
        env_key = spec.get("env_key")
        if provider not in _VALID_PROVIDERS:
            continue
        if not (isinstance(model_id, str) and model_id and isinstance(env_key, str) and env_key):
            continue
        base_url = spec.get("base_url")
        reasoning_effort = spec.get("reasoning_effort")
        out[key] = ModelConfig(
            provider=provider,
            model_id=model_id,
            env_key=env_key,
            base_url=base_url if isinstance(base_url, str) else None,
            thinking=bool(spec.get("thinking", False)),
            reasoning_effort=reasoning_effort if isinstance(reasoning_effort, str) else None,
        )
    return out


def resolve_models(project_dir: Path | str) -> dict[str, ModelConfig]:
    """Return builtin models merged with project overrides (overrides win)."""
    return {**BUILTIN_MODELS, **load_model_overrides(project_dir)}


def model_summary(models_map: dict[str, ModelConfig]) -> list[dict]:
    """Describe available models for discovery (CLI/MCP 'list models')."""
    builtin_keys = set(BUILTIN_MODELS)
    return [
        {
            "key": key,
            "provider": cfg.provider,
            "model_id": cfg.model_id,
            "env_key": cfg.env_key,
            "key_present": bool(os.environ.get(cfg.env_key)),
            "thinking": cfg.thinking or cfg.reasoning_effort is not None,
            "source": "builtin" if key in builtin_keys else "custom",
        }
        for key, cfg in models_map.items()
    ]


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

    is_reasoning = config.reasoning_effort is not None

    api_messages = []
    if system_prompt:
        if is_reasoning:
            # Reasoning models (e.g. GPT-5.x) take a developer message, not system.
            api_messages.append({"role": "developer", "content": system_prompt})
        else:
            api_messages.append({"role": "system", "content": system_prompt})
    api_messages.extend(messages)

    create_kwargs: dict = {"model": config.model_id, "messages": api_messages}
    if config.reasoning_effort:
        create_kwargs["reasoning_effort"] = config.reasoning_effort

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
        # Gemini 3.x reasons by default; don't pin a thinking_budget/level
        # (the parameter shape changed across SDK versions). Just allow more
        # time for the longer thinking turn.
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
        # Adaptive thinking: current Claude models (Opus 4.8 / Sonnet 5) reject
        # {"type": "enabled", "budget_tokens": N} with a 400 — budget_tokens is
        # removed. Adaptive is the only on-mode; the model paces its own depth.
        body["thinking"] = {"type": "adaptive"}

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
    models: dict[str, ModelConfig] | None = None,
) -> str:
    """Send conversation history to a model, return response text.

    Args:
        model_key: Key from the models map (e.g., "gpt", "gemini-pro", "claude-opus")
        messages: List of {"role": "user"|"assistant", "content": "..."} dicts
        system_prompt: Optional system/context prompt
        models: Resolved models map (builtins + project overrides). Defaults to
            the builtin set when not provided.
    """
    models = models or MODELS
    if model_key not in models:
        raise ValueError(f"Unknown model: {model_key}. Available: {list(models.keys())}")

    config = models[model_key]
    dispatch_fn = _DISPATCH[config.provider]
    return dispatch_fn(config, messages, system_prompt)
