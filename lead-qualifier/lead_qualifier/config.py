"""Configuration + secrets loading and validation.

Secrets come from the environment (optionally seeded by a .env file); the key
required for the chosen provider is validated at startup and missing keys fail
loudly by name. The active LLM provider is selected with ``LLM_PROVIDER``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# Default Anthropic model — a current, highly capable Claude model. For
# high-volume runs, claude-sonnet-4-6 or claude-haiku-4-5 cut cost (see README).
DEFAULT_MODEL = "claude-opus-4-8"


# Supported LLM providers. Everything except "anthropic" is reached through one
# OpenAI-compatible client (see llm.py), differing only by base_url, default
# model, and which env var holds the key. A free key works great here — Gemini
# (aistudio.google.com) and Groq (console.groq.com) both have generous free tiers.
PROVIDER_PRESETS: dict[str, dict] = {
    "anthropic": {
        "base_url": None,
        "default_model": DEFAULT_MODEL,
        "key_envs": ["ANTHROPIC_API_KEY"],
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "key_envs": ["OPENAI_API_KEY"],
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "key_envs": ["GROQ_API_KEY"],
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.0-flash",
        "key_envs": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    },
}


class ConfigError(RuntimeError):
    """Raised when configuration / secrets are missing or invalid."""


@dataclass
class Settings:
    llm_api_key: str
    llm_provider: str = "anthropic"
    model: str = DEFAULT_MODEL
    base_url: str | None = None
    score_threshold: int = 6
    request_delay: float = 1.0
    max_workers: int = 4
    theirstack_api_key: str | None = None
    scraper_api_key: str | None = None
    user_agent: str = (
        "LeadQualifierBot/1.0 (+https://example.com/bot; polite research crawler)"
    )

    # Optional providers — presence only needed when the matching flag is used.
    def require_history_api(self) -> None:
        if not self.theirstack_api_key:
            raise ConfigError(
                "History provider 'api' selected but THEIRSTACK_API_KEY is not set "
                "in your .env file. Either set it or use --history-provider none."
            )


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        raise ConfigError(f"Env var {name} must be a number, got: {val!r}")


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        raise ConfigError(f"Env var {name} must be an integer, got: {val!r}")


def _resolve_key(preset: dict) -> str:
    """First non-empty provider-specific key env, else the generic LLM_API_KEY."""
    for env in preset["key_envs"]:
        val = os.getenv(env, "").strip()
        if val:
            return val
    return os.getenv("LLM_API_KEY", "").strip()


def load_settings(env_file: str | Path | None = None, *, validate_keys: bool = True) -> Settings:
    """Load settings from .env + environment.

    Args:
        env_file: explicit path to a .env file; otherwise auto-discovered.
        validate_keys: if True, require the chosen provider's API key to be present.
    """
    if env_file:
        load_dotenv(env_file, override=False)
    else:
        load_dotenv(override=False)

    provider = os.getenv("LLM_PROVIDER", "anthropic").strip().lower() or "anthropic"
    if provider not in PROVIDER_PRESETS:
        raise ConfigError(
            f"Unknown LLM_PROVIDER={provider!r}. "
            f"Choose one of: {', '.join(sorted(PROVIDER_PRESETS))}."
        )
    preset = PROVIDER_PRESETS[provider]

    api_key = _resolve_key(preset)
    if validate_keys and not api_key:
        expected = " or ".join(preset["key_envs"]) + " (or LLM_API_KEY)"
        raise ConfigError(
            f"Missing API key for LLM_PROVIDER='{provider}'. "
            f"Set {expected} in your environment / .env file."
        )

    # Model: explicit LLM_MODEL wins; ANTHROPIC_MODEL still honoured for Claude;
    # otherwise the provider's sensible default.
    model = os.getenv("LLM_MODEL", "").strip()
    if not model and provider == "anthropic":
        model = os.getenv("ANTHROPIC_MODEL", "").strip()
    if not model:
        model = preset["default_model"]

    base_url = os.getenv("LLM_BASE_URL", "").strip() or preset["base_url"]

    return Settings(
        llm_api_key=api_key,
        llm_provider=provider,
        model=model,
        base_url=base_url,
        score_threshold=_env_int("SCORE_THRESHOLD", 6),
        request_delay=_env_float("REQUEST_DELAY", 1.0),
        max_workers=_env_int("MAX_WORKERS", 4),
        theirstack_api_key=os.getenv("THEIRSTACK_API_KEY", "").strip() or None,
        scraper_api_key=os.getenv("SCRAPER_API_KEY", "").strip() or None,
    )


# Path to bundled prompt templates.
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt template by filename (without extension) from prompts/."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise ConfigError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")
