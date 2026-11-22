"""OpenAI speech synthesis — POST /v1/audio/speech."""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..providers.base import post_bytes
from .accents import instructions_for

API_URL = "https://api.openai.com/v1/audio/speech"

ENGINE = "openai tts"
REQUIRED_SETTINGS: tuple[str, ...] = ("openai_api_key", "tts_model", "tts_voice")


def supports_instructions(model: str) -> bool:
    """Only the gpt-4o speech models accept a style/accent instruction.

    The older tts-1 family rejects the field, so accent control there is
    limited to whichever voice is chosen.
    """
    return model.startswith("gpt-")


def _request(text: str, accent: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    settings = get_settings()

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key or ''}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": settings.tts_model,
        "voice": settings.tts_voice,
        "input": text,
        "response_format": "mp3",
    }
    if supports_instructions(settings.tts_model):
        payload["instructions"] = instructions_for(accent)

    return API_URL, headers, payload


async def synthesize(text: str, accent: str) -> bytes:
    url, headers, payload = _request(text, accent)
    return await post_bytes(url, headers, payload, provider=ENGINE)
