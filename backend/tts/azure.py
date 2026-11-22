"""Azure OpenAI speech synthesis.

Same request body as OpenAI; the deployment lives in the URL and the key
travels in an ``api-key`` header.
"""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..providers.base import post_bytes
from .accents import instructions_for
from .openai import supports_instructions

ENGINE = "azure tts"
REQUIRED_SETTINGS: tuple[str, ...] = (
    "azure_openai_api_key",
    "azure_openai_endpoint",
    "azure_tts_deployment",
    "azure_tts_api_version",
)


def _build_url() -> str:
    settings = get_settings()
    endpoint = (settings.azure_openai_endpoint or "").rstrip("/")
    return (
        f"{endpoint}/openai/deployments/{settings.azure_tts_deployment}"
        f"/audio/speech?api-version={settings.azure_tts_api_version}"
    )


def _request(text: str, accent: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    settings = get_settings()

    headers = {
        "api-key": settings.azure_openai_api_key or "",
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

    return _build_url(), headers, payload


async def synthesize(text: str, accent: str) -> bytes:
    url, headers, payload = _request(text, accent)
    return await post_bytes(url, headers, payload, provider=ENGINE)
