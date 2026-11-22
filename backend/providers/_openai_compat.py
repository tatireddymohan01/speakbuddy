"""Helpers for the OpenAI-style ``/chat/completions`` wire format.

Both OpenAI and Azure OpenAI speak it (as do several third-party gateways), so
the message shaping and reply parsing live here rather than being duplicated.
The leading underscore keeps this module out of provider discovery.
"""

from __future__ import annotations

from typing import Any

from .base import ProviderError


def build_messages(messages: list[dict[str, str]], system_prompt: str) -> list[dict[str, str]]:
    """Prepend the system prompt to the conversation."""
    return [{"role": "system", "content": system_prompt}, *messages]


# Newer OpenAI model families renamed the output cap and stopped accepting a
# custom temperature. Sending the old field to them is a hard 400.
_NEW_PARAM_FAMILIES = ("gpt-5", "o1", "o3", "o4")


def uses_new_params(model: str) -> bool:
    return model.lower().startswith(_NEW_PARAM_FAMILIES)


def token_limit_field(model: str) -> str:
    """The parameter name this model expects for its output cap."""
    return "max_completion_tokens" if uses_new_params(model) else "max_tokens"


def build_payload(
    model: str,
    messages: list[dict[str, str]],
    system_prompt: str,
    max_tokens: int,
    temperature: float | None,
) -> dict[str, Any]:
    """Assemble a chat-completions body valid for this model generation."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": build_messages(messages, system_prompt),
        token_limit_field(model): max_tokens,
    }

    # Reasoning models reject anything but the default temperature, so it is
    # only sent when explicitly configured and the model still accepts it.
    if temperature is not None and not uses_new_params(model):
        payload["temperature"] = temperature

    return payload


def parse_reply(body: dict[str, Any], provider: str) -> str:
    """Pull the assistant text out of a chat-completions response."""
    choices = body.get("choices") or []
    if not choices:
        raise ProviderError(
            f"{provider.capitalize()} returned no reply. Please try again.",
            status_code=502,
            retryable=True,
        )

    text = (choices[0].get("message") or {}).get("content") or ""
    text = text.strip()
    if not text:
        raise ProviderError(
            f"{provider.capitalize()} returned an empty reply. Please try again.",
            status_code=502,
            retryable=True,
        )
    return text
