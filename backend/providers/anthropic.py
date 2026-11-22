"""Anthropic (Claude) provider — Messages API over raw httpx."""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from .base import ProviderError, post_json

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

PROVIDER = "anthropic"
REQUIRED_SETTINGS: tuple[str, ...] = ("anthropic_api_key", "anthropic_model")


def _normalise(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Anthropic requires the conversation to open on a user turn.

    The frontend greets the learner with a tutor line before they have said
    anything, so drop any assistant turns that lead the history.
    """
    index = 0
    while index < len(messages) and messages[index]["role"] != "user":
        index += 1
    return messages[index:]


def _extract_text(body: dict[str, Any]) -> str:
    blocks = body.get("content") or []
    text = "".join(
        block.get("text", "") for block in blocks if block.get("type") == "text"
    ).strip()

    if not text:
        # A refusal or a max_tokens cut can both land here.
        stop_reason = body.get("stop_reason")
        if stop_reason == "refusal":
            raise ProviderError(
                "The tutor could not respond to that. Try rephrasing.",
                status_code=502,
            )
        raise ProviderError(
            "Claude returned an empty reply. Please try again.",
            status_code=502,
            retryable=True,
        )
    return text


async def get_reply(messages: list[dict[str, str]], system_prompt: str) -> str:
    settings = get_settings()

    conversation = _normalise(messages)
    if not conversation:
        raise ProviderError("No user message to respond to.", status_code=400)

    headers = {
        "x-api-key": settings.anthropic_api_key or "",
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": settings.anthropic_model,
        "max_tokens": settings.max_tokens,
        # The system prompt is a top-level field on Anthropic, not a message.
        "system": system_prompt,
        "messages": conversation,
        # Spoken conversation is latency-sensitive and these replies are short,
        # so skip extended reasoning. Current Claude models think by default.
        # (Remove this key if you point ANTHROPIC_MODEL at a model that
        # requires thinking to stay on.)
        "thinking": {"type": "disabled"},
    }

    body = await post_json(API_URL, headers, payload, provider=PROVIDER)
    return _extract_text(body)
