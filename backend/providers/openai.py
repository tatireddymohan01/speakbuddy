"""OpenAI (GPT) provider — Chat Completions API over raw httpx."""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from ._openai_compat import build_payload, parse_reply
from .base import post_json

API_URL = "https://api.openai.com/v1/chat/completions"

PROVIDER = "openai"
REQUIRED_SETTINGS: tuple[str, ...] = ("openai_api_key", "openai_model")


async def get_reply(messages: list[dict[str, str]], system_prompt: str) -> str:
    settings = get_settings()

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key or ''}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = build_payload(
        settings.openai_model,
        messages,
        system_prompt,
        settings.max_tokens,
        settings.temperature,
    )

    body = await post_json(API_URL, headers, payload, provider=PROVIDER)
    return parse_reply(body, PROVIDER)
