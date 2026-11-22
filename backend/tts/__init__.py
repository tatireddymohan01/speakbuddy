"""Text-to-speech engine registry.

Mirrors backend/providers: engines are discovered by scanning this package, so
adding a fourth speech backend means adding one file.

An engine module must expose:

    REQUIRED_SETTINGS: tuple[str, ...]
    async def synthesize(text: str, accent: str) -> bytes   # MP3 audio
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from ..config import Settings
from ..providers.base import ProviderConfigError, require
from .accents import ACCENTS, DEFAULT_ACCENT, catalogue, instructions_for, normalise

__all__ = [
    "ACCENTS",
    "DEFAULT_ACCENT",
    "available_engines",
    "catalogue",
    "instructions_for",
    "load_engine",
    "normalise",
    "validate_engine",
]

_NON_ENGINE_MODULES = {"accents"}


def available_engines() -> list[str]:
    """Names of every speech engine module in this package."""
    return sorted(
        module.name
        for module in pkgutil.iter_modules(__path__)
        if not module.name.startswith("_") and module.name not in _NON_ENGINE_MODULES
    )


def load_engine(name: str) -> ModuleType:
    """Import a speech engine module by name."""
    normalised = (name or "").strip().lower()
    if normalised not in available_engines():
        raise ProviderConfigError(
            f"Unknown TTS_PROVIDER={name!r}. "
            f"Available speech engines: {', '.join(available_engines())}."
        )

    module = importlib.import_module(f"{__name__}.{normalised}")
    if not hasattr(module, "synthesize"):
        raise ProviderConfigError(
            f"Speech engine {normalised!r} does not define synthesize()."
        )
    return module


def validate_engine(name: str, settings: Settings) -> ModuleType:
    """Load a speech engine and check its required settings are present."""
    module = load_engine(name)
    require(settings, getattr(module, "REQUIRED_SETTINGS", ()), f"{name} (tts)")
    return module
