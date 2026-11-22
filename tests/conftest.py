"""Shared test setup.

The app validates its provider at startup, so tests give it obviously fake
credentials and swap the provider for a stub — no test ever calls a real API.
"""

from __future__ import annotations

import os

# Must run before backend.config is imported: settings are read once and
# cached. Real environment variables also override a local .env file.
os.environ.update(
    {
        "LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "test-key-not-real",
        "TTS_ENABLED": "false",
        "ALLOWED_ORIGINS": "",
    }
)

import pytest
from fastapi.testclient import TestClient


class FakeProvider:
    """Stands in for a provider module; records every call it receives."""

    def __init__(self, reply: str = "Nice! We'd say: I went to the market.") -> None:
        self.reply = reply
        self.calls: list[tuple[list[dict], str]] = []

    async def get_reply(self, messages: list[dict], system_prompt: str) -> str:
        self.calls.append((messages, system_prompt))
        return self.reply


@pytest.fixture
def client():
    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def fake_provider(client):
    """Replace the real provider after startup validation has passed."""
    provider = FakeProvider()
    client.app.state.provider = provider
    return provider
