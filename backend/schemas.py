"""Request and response models for the public API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("content cannot be blank")
        return cleaned


Mode = Literal["casual", "lesson", "correction"]


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=100)
    # Speech Correction is the default: the frontend always sends a mode, so
    # this only applies to a client that omits it.
    mode: Mode = "correction"

    @field_validator("messages")
    @classmethod
    def _must_end_on_user(cls, value: list[Message]) -> list[Message]:
        if value[-1].role != "user":
            raise ValueError("the final message must have role 'user'")
        return value


class ChatResponse(BaseModel):
    reply: str
    mode: Mode


class SpeakRequest(BaseModel):
    """A block of tutor text to render as speech."""

    text: str = Field(min_length=1, max_length=1500)
    accent: str = "us"

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text cannot be blank")
        return cleaned


class ErrorResponse(BaseModel):
    error: str
    retryable: bool = False
