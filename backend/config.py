"""Application configuration.

Every secret and provider choice lives here, loaded from the environment (or a
local ``.env``). Nothing in this module is ever serialised to the frontend.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings.

    Field names map to upper-case environment variables case-insensitively, so
    ``anthropic_api_key`` is populated from ``ANTHROPIC_API_KEY``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Which provider module under backend/providers/ handles the request.
    llm_provider: str = "anthropic"

    # Anthropic
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    # OpenAI
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"

    # Azure OpenAI
    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"

    # ── Text to speech ──────────────────────────────────────────────────
    # Speech is generated on the server so every device sounds identical —
    # browser voices differ per OS and often lack UK/Indian English entirely.
    tts_enabled: bool = True
    tts_provider: str = "openai"        # module name under backend/tts/
    tts_model: str = "gpt-4o-mini-tts"  # supports accent via `instructions`
    tts_voice: str = "alloy"
    tts_accent: str = "us"              # default; the user can switch per turn

    # Azure only: the deployment serving the speech model.
    azure_tts_deployment: str | None = None
    azure_tts_api_version: str = "2025-03-01-preview"

    # Generation + transport tuning.
    # Speech Correction replies are the longest, so the cap has headroom; other
    # modes stay short on their own. You only pay for tokens actually produced.
    max_tokens: int = 700

    # Left unset by default: the gpt-5 / o-series models reject any value but
    # their own default, so nothing is sent unless you opt in.
    temperature: float | None = None
    request_timeout_seconds: float = 45.0

    # Conversation turns kept when relaying history upstream (user + assistant).
    max_history_messages: int = 20

    # Comma-separated origins. Leave empty when FastAPI serves the frontend.
    allowed_origins: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
