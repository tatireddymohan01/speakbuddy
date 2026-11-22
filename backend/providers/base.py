"""Shared plumbing for LLM providers.

A provider module only needs to build a URL, headers and a payload, then pull
the reply text out of the JSON. Transport, timeouts, and turning upstream
failures into safe user-facing errors all happen here so every provider behaves
identically.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

# Anything that looks like a credential, redacted before an upstream message is
# allowed anywhere near a response or a log line.
_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{8,}|[A-Za-z0-9]{32,})"
)


def redact(text: str) -> str:
    """Mask anything credential-shaped in `text`."""
    return _SECRET_PATTERN.sub("[redacted]", text)


_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """The shared HTTP client.

    Reused across requests so connections stay alive: opening a fresh client
    per call meant a new TLS handshake every time, which measured ~3 seconds
    of pure overhead per chat-plus-speech turn.
    """
    global _client
    if _client is None or _client.is_closed:
        settings = get_settings()
        _client = httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
                keepalive_expiry=300.0,
            ),
        )
    return _client


async def close_client() -> None:
    """Close the shared client at shutdown."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class ProviderConfigError(Exception):
    """Raised at startup when the selected provider is misconfigured."""


class ProviderError(Exception):
    """An upstream failure, already translated into something safe to show."""

    def __init__(self, message: str, status_code: int = 502, *, retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


def _friendly_error(status: int, provider: str, upstream: str) -> ProviderError:
    """Map an upstream HTTP status onto a message a learner can act on."""
    label = provider.capitalize()

    if status in (401, 403):
        return ProviderError(
            f"{label} rejected the API key. Check the key configured on the server.",
            status_code=502,
        )
    if status == 404:
        return ProviderError(
            f"{label} could not find that model or deployment. "
            f"Check the model name on the server. ({upstream})",
            status_code=502,
        )
    if status == 429:
        return ProviderError(
            f"{label} is rate limiting requests right now. Wait a moment and try again.",
            status_code=429,
            retryable=True,
        )
    if status in (400, 422):
        return ProviderError(
            f"{label} rejected the request. ({upstream})",
            status_code=502,
        )
    if status >= 500:
        return ProviderError(
            f"{label} is having trouble right now. Please try again shortly.",
            status_code=502,
            retryable=True,
        )
    return ProviderError(
        f"{label} returned an unexpected error (HTTP {status}).",
        status_code=502,
    )


def _extract_upstream_message(response: httpx.Response) -> str:
    """Pull a short, redacted error string out of an upstream error body."""
    try:
        body = response.json()
    except ValueError:
        return redact(response.text)[:200]

    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("type") or ""
        elif isinstance(error, str):
            message = error
        else:
            message = body.get("message", "")
        return redact(str(message))[:200]
    return ""


async def post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    provider: str,
) -> dict[str, Any]:
    """POST JSON and return the decoded body, or raise a `ProviderError`.

    Request headers are never logged — they carry the API key.
    """
    try:
        response = await get_client().post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        logger.warning("%s request timed out", provider)
        raise ProviderError(
            f"{provider.capitalize()} took too long to respond. Please try again.",
            status_code=504,
            retryable=True,
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("%s transport error: %s", provider, redact(str(exc)))
        raise ProviderError(
            f"Could not reach {provider.capitalize()}. Check the server's network connection.",
            status_code=502,
            retryable=True,
        ) from exc

    if response.status_code >= 400:
        upstream = _extract_upstream_message(response)
        logger.warning(
            "%s returned HTTP %s: %s", provider, response.status_code, upstream
        )
        raise _friendly_error(response.status_code, provider, upstream)

    try:
        return response.json()
    except ValueError as exc:
        logger.warning("%s returned a non-JSON body", provider)
        raise ProviderError(
            f"{provider.capitalize()} returned a malformed response.",
            status_code=502,
        ) from exc


async def post_bytes(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    provider: str,
) -> bytes:
    """POST JSON and return raw bytes — used by the speech endpoints.

    Shares the timeout and error-mapping behaviour of `post_json`; only the
    success path differs, because audio comes back as binary.
    """
    try:
        response = await get_client().post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        logger.warning("%s request timed out", provider)
        raise ProviderError(
            f"{provider.capitalize()} took too long to respond. Please try again.",
            status_code=504,
            retryable=True,
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("%s transport error: %s", provider, redact(str(exc)))
        raise ProviderError(
            f"Could not reach {provider.capitalize()}.",
            status_code=502,
            retryable=True,
        ) from exc

    if response.status_code >= 400:
        upstream = _extract_upstream_message(response)
        logger.warning(
            "%s returned HTTP %s: %s", provider, response.status_code, upstream
        )
        raise _friendly_error(response.status_code, provider, upstream)

    if not response.content:
        raise ProviderError(
            f"{provider.capitalize()} returned empty audio.",
            status_code=502,
            retryable=True,
        )
    return response.content


def require(settings_obj: Any, names: tuple[str, ...], provider: str) -> None:
    """Raise `ProviderConfigError` naming every missing setting."""
    missing = [n.upper() for n in names if not getattr(settings_obj, n, None)]
    if missing:
        raise ProviderConfigError(
            f"LLM_PROVIDER={provider} requires these environment variables: "
            + ", ".join(missing)
        )
