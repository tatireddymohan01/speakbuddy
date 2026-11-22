"""Azure OpenAI Service provider.

Same wire format as OpenAI, but the deployment name lives in the URL and the
key travels in an ``api-key`` header instead of ``Authorization``.
"""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from ._openai_compat import build_payload, parse_reply
from .base import post_json

PROVIDER = "azure"
REQUIRED_SETTINGS: tuple[str, ...] = (
    "azure_openai_api_key",
    "azure_openai_endpoint",
    "azure_openai_deployment",
    "azure_openai_api_version",
)


def _build_url() -> str:
    settings = get_settings()
    endpoint = (settings.azure_openai_endpoint or "").rstrip("/")
    return (
        f"{endpoint}/openai/deployments/{settings.azure_openai_deployment}"
        f"/chat/completions?api-version={settings.azure_openai_api_version}"
    )


async def get_reply(messages: list[dict[str, str]], system_prompt: str) -> str:
    settings = get_settings()

    headers = {
        "api-key": settings.azure_openai_api_key or "",
        "Content-Type": "application/json",
    }

    # The deployment name selects the model, so `model` in the body is unused;
    # the deployment is still passed so parameter names match its generation.
    payload: dict[str, Any] = build_payload(
        settings.azure_openai_deployment or "",
        messages,
        system_prompt,
        settings.max_tokens,
        settings.temperature,
    )
    payload.pop("model", None)

    body = await post_json(_build_url(), headers, payload, provider=PROVIDER)
    return parse_reply(body, PROVIDER)
