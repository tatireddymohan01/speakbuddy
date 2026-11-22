"""SpeakBuddy FastAPI application.

Serves the static frontend and exposes a single chat endpoint. All provider
credentials stay in this process — the browser never sees a key, a provider
name, or an upstream URL.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .prompts import build_system_prompt
from .providers import ProviderConfigError, ProviderError, validate_provider
from .providers.base import close_client
from .schemas import ChatRequest, ChatResponse, SpeakRequest
from .tts import catalogue, normalise, validate_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("speakbuddy")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Fail fast if the selected provider is missing or misconfigured."""
    settings = get_settings()
    try:
        provider = validate_provider(settings.llm_provider, settings)
    except ProviderConfigError as exc:
        logger.error("Startup aborted - %s", exc)
        logger.error("Copy .env.example to .env and fill in the missing values.")
        raise

    app.state.provider = provider

    # Speech is optional: if it is misconfigured the chat must still work, so
    # this warns and disables rather than aborting startup.
    app.state.tts = None
    if settings.tts_enabled:
        try:
            app.state.tts = validate_engine(settings.tts_provider, settings)
        except ProviderConfigError as exc:
            logger.warning("Server speech disabled - %s", exc)
            logger.warning("The browser's own voices will be used instead.")

    # Plain ASCII here: Windows consoles mangle non-ASCII log output.
    logger.info(
        "SpeakBuddy ready - provider=%s, speech=%s",
        settings.llm_provider.strip().lower(),
        settings.tts_provider.strip().lower() if app.state.tts else "browser",
    )

    yield

    await close_client()


app = FastAPI(
    title="SpeakBuddy",
    description="AI-assisted spoken English practice tutor.",
    version="1.0.0",
    lifespan=lifespan,
)

# Only needed when the frontend is served from a different origin.
_origins = get_settings().cors_origins
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )


# ── Error handling ──────────────────────────────────────────────────────────


@app.exception_handler(ProviderError)
async def _provider_error_handler(_: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message, "retryable": exc.retryable},
    )


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    logger.info("Rejected malformed request: %s", exc.errors())
    return JSONResponse(
        status_code=422,
        content={"error": "That request was not formed correctly.", "retryable": False},
    )


@app.exception_handler(Exception)
async def _unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    # Log the detail server-side; the client gets nothing but a safe message.
    logger.exception("Unhandled error: %s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Something went wrong on the server. Please try again.",
            "retryable": True,
        },
    )


# ── API ─────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check. Reports that a provider is configured, not which one."""
    return {"status": "ok", "provider_configured": "true"}


@app.get("/api/config")
async def client_config() -> dict[str, object]:
    """What the frontend needs to know. Never names the provider or a key."""
    settings = get_settings()
    return {
        "server_speech": app.state.tts is not None,
        "accents": catalogue(),
        "default_accent": normalise(settings.tts_accent),
    }


async def _speech_response(text: str, accent: str) -> Response:
    """Return one complete audio clip, with a Content-Length.

    Deliberately *not* streamed. An <audio> element asks for byte ranges and
    needs a length to know where the clip ends; a chunked response with
    neither made Chrome stop before the final sentence. The frontend keeps
    latency down by requesting the reply in short segments instead.
    """
    if app.state.tts is None:
        raise ProviderError(
            "Server speech is not configured.", status_code=503, retryable=False
        )

    audio = await app.state.tts.synthesize(text, normalise(accent))
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store",
            "Content-Length": str(len(audio)),
            "Accept-Ranges": "none",
        },
    )


@app.get("/api/speak")
async def speak_get(text: str, accent: str = "us") -> Response:
    """GET form, so an <audio> element can use the URL as its source."""
    cleaned = text.strip()
    if not cleaned or len(cleaned) > 1500:
        raise ProviderError("Nothing to speak.", status_code=422, retryable=False)
    return await _speech_response(cleaned, accent)


@app.post("/api/speak")
async def speak(request: SpeakRequest) -> Response:
    """POST form, used when the text is too long for a URL."""
    return await _speech_response(request.text, request.accent)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Return the tutor's next spoken turn."""
    settings = get_settings()

    # Trim to the most recent turns so context stays bounded and cheap.
    recent = request.messages[-settings.max_history_messages :]
    payload = [{"role": m.role, "content": m.content} for m in recent]

    system_prompt = build_system_prompt(request.mode)
    reply = await app.state.provider.get_reply(payload, system_prompt)

    return ChatResponse(reply=reply, mode=request.mode)


# ── Static frontend ─────────────────────────────────────────────────────────
# Mounted last so it never shadows /api or /health.

if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:  # pragma: no cover - only hit if the checkout is incomplete
    logger.warning("Frontend directory not found at %s", FRONTEND_DIR)
