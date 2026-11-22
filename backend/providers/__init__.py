"""Provider registry.

Providers are discovered dynamically from this package, so adding a fourth
backend means dropping in one new file — nothing else in the codebase changes.

A provider module must expose:

    REQUIRED_SETTINGS: tuple[str, ...]
        Settings field names that must be non-empty for this provider.

    async def get_reply(messages: list[dict], system_prompt: str) -> str
        Return the assistant's reply text.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from ..config import Settings
from .base import ProviderConfigError, ProviderError, require

__all__ = [
    "ProviderConfigError",
    "ProviderError",
    "available_providers",
    "load_provider",
    "validate_provider",
]

# Module names in this package that are infrastructure, not providers.
_NON_PROVIDER_MODULES = {"base"}


def available_providers() -> list[str]:
    """Names of every provider module in this package."""
    return sorted(
        module.name
        for module in pkgutil.iter_modules(__path__)
        if not module.name.startswith("_") and module.name not in _NON_PROVIDER_MODULES
    )


def load_provider(name: str) -> ModuleType:
    """Import a provider module by name."""
    normalised = (name or "").strip().lower()
    if normalised not in available_providers():
        raise ProviderConfigError(
            f"Unknown LLM_PROVIDER={name!r}. "
            f"Available providers: {', '.join(available_providers())}."
        )

    module = importlib.import_module(f"{__name__}.{normalised}")

    if not hasattr(module, "get_reply"):
        raise ProviderConfigError(
            f"Provider module {normalised!r} does not define get_reply()."
        )
    return module


def validate_provider(name: str, settings: Settings) -> ModuleType:
    """Load a provider and fail fast if its required settings are missing."""
    module = load_provider(name)
    require(settings, getattr(module, "REQUIRED_SETTINGS", ()), name.strip().lower())
    return module
