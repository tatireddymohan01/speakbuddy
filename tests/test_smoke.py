"""Smoke tests: the app starts, serves its pages, and guards its API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

USER_TURN = {"role": "user", "content": "I go to market yesterday"}


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider_configured": "true"}


def test_frontend_is_served(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_client_config_never_reveals_provider_or_key(client):
    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["server_speech"] is False  # TTS disabled in tests
    body = response.text.lower()
    assert "openai" not in body
    assert "test-key-not-real" not in body


def test_chat_returns_provider_reply(client, fake_provider):
    response = client.post("/api/chat", json={"messages": [USER_TURN], "mode": "lesson"})

    assert response.status_code == 200
    assert response.json() == {"reply": fake_provider.reply, "mode": "lesson"}
    assert len(fake_provider.calls) == 1
    messages, system_prompt = fake_provider.calls[0]
    assert messages == [USER_TURN]
    assert system_prompt  # built server-side from the mode


@pytest.mark.parametrize(
    "payload",
    [
        {"messages": []},
        {"messages": [{"role": "assistant", "content": "Hi!"}]},  # must end on user
        {"messages": [{"role": "user", "content": "   "}]},  # blank content
        {"messages": [USER_TURN], "mode": "not-a-mode"},
    ],
)
def test_chat_rejects_malformed_requests(client, fake_provider, payload):
    response = client.post("/api/chat", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "error": "That request was not formed correctly.",
        "retryable": False,
    }
    assert fake_provider.calls == []  # nothing reached the provider


def test_speak_reports_unavailable_when_tts_disabled(client):
    response = client.post("/api/speak", json={"text": "Hello"})

    assert response.status_code == 503
    assert response.json()["retryable"] is False


def test_startup_refuses_missing_provider_key(monkeypatch):
    """The README promises the app will not start half-configured."""
    from backend.config import get_settings
    from backend.main import app
    from backend.providers import ProviderConfigError

    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(ProviderConfigError, match="OPENAI_API_KEY"), TestClient(app):
            pass
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
