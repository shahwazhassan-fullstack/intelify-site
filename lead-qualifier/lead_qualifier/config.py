"""Configuration + secrets loading and validation.

All secrets come from a .env file (never hardcoded). Presence of required
keys is validated at startup; missing keys fail loudly by name.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# Default model — a current, highly capable Claude model. Configurable via
# ANTHROPIC_MODEL in .env. For high-volume runs, claude-sonnet-4-6 or
# claude-haiku-4-5 cut cost substantially (see README).
DEFAULT_MODEL = "claude-opus-4-8"


class ConfigError(RuntimeError):
    """Raised when configuration / secrets are missing or invalid."""


@dataclass
class Settings:
    anthropic_api_key: str
    model: str = DEFAULT_MODEL
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


def load_settings(env_file: str | Path | None = None, *, validate_keys: bool = True) -> Settings:
    """Load settings from .env + environment.

    Args:
        env_file: explicit path to a .env file; otherwise auto-discovered.
        validate_keys: if True, require ANTHROPIC_API_KEY to be present.
    """
    if env_file:
        load_dotenv(env_file, override=False)
    else:
        load_dotenv(override=False)

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if validate_keys and not api_key:
        raise ConfigError(
            "Missing required environment variable: ANTHROPIC_API_KEY. "
            "Copy .env.example to .env and fill it in."
        )

    return Settings(
        anthropic_api_key=api_key,
        model=os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
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
