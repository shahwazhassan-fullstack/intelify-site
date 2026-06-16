"""LLM provider abstraction.

The pipeline only needs one operation — send a prompt, get text back — so it
talks to a tiny ``LLMClient`` interface. The concrete client is chosen by
configuration (``LLM_PROVIDER``), letting the same pipeline run on Anthropic
(Claude) or any OpenAI-compatible API (Google Gemini, Groq, OpenAI) without
changing the research / qualify / assemble steps.

Providers and their OpenAI-compatible endpoints are declared in
``config.PROVIDER_PRESETS``; everything except Anthropic is reached through the
one ``OpenAICompatClient`` below.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)


def _is_transient(exc: BaseException) -> bool:
    """True for errors worth retrying (rate limits, timeouts, 5xx, overload).

    Matched by class name + message so it works across the Anthropic and
    OpenAI SDKs without importing their exception types here.
    """
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    if any(k in name for k in ("ratelimit", "timeout", "connection", "internalserver", "serviceunavailable", "apistatus")):
        return True
    return any(
        k in msg
        for k in ("rate limit", "rate_limit", "429", "timeout", "timed out",
                  "temporarily", "overloaded", "try again", "500", "502", "503", "504")
    )


# Shared retry policy: free tiers throttle aggressively, so back off and retry
# transient failures; auth/4xx errors fail fast.
_with_retries = retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception(_is_transient),
)


@runtime_checkable
class LLMClient(Protocol):
    """Minimal interface the pipeline depends on."""

    model: str

    def complete(self, prompt: str, *, max_tokens: int) -> str:
        """Send a single user prompt and return the model's text reply."""
        ...


class AnthropicClient:
    """Claude via the Anthropic Messages API."""

    def __init__(self, api_key: str, model: str):
        from anthropic import Anthropic  # imported lazily so other providers don't need it

        self._client = Anthropic(api_key=api_key)
        self.model = model

    @_with_retries
    def complete(self, prompt: str, *, max_tokens: int) -> str:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "\n".join(parts).strip()


class OpenAICompatClient:
    """Any OpenAI-compatible Chat Completions API.

    Covers OpenAI, Google Gemini (its OpenAI-compatible endpoint), and Groq —
    they differ only by ``base_url``, ``model``, and API key.
    """

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        from openai import OpenAI  # imported lazily so the Anthropic path doesn't need it

        self._client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self.model = model

    @_with_retries
    def complete(self, prompt: str, *, max_tokens: int) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return (resp.choices[0].message.content or "").strip()


def build_llm_client(settings) -> LLMClient:
    """Construct the configured LLM client from Settings."""
    if settings.llm_provider == "anthropic":
        return AnthropicClient(settings.llm_api_key, settings.model)
    return OpenAICompatClient(settings.llm_api_key, settings.model, settings.base_url)
