"""Accent catalogue for server-side speech.

Adding an accent is one entry here — it appears in the API, the frontend
picker, and the synthesis instruction automatically.
"""

from __future__ import annotations

# key -> (label shown in the UI, how the voice should sound)
ACCENTS: dict[str, tuple[str, str]] = {
    "us": ("American English", "a clear, natural American English accent"),
    "uk": ("British English", "a clear British English accent, Received Pronunciation"),
    "in": ("Indian English", "a clear, natural Indian English accent"),
    "au": ("Australian English", "a clear Australian English accent"),
    "ca": ("Canadian English", "a clear Canadian English accent"),
    "ie": ("Irish English", "a clear Irish English accent"),
}

DEFAULT_ACCENT = "us"

# The tutor persona, applied on top of whichever accent is selected.
_TONE = (
    "You are a warm, encouraging English tutor speaking to someone practising "
    "the language out loud. Speak at a slightly measured pace with clear "
    "articulation so every word is easy to catch, and sound friendly and "
    "patient rather than formal. Do not read out any labels, punctuation or "
    "formatting - just speak the words naturally."
)


def normalise(accent: str | None) -> str:
    """Return a supported accent key, falling back to the default."""
    key = (accent or "").strip().lower()
    return key if key in ACCENTS else DEFAULT_ACCENT


def instructions_for(accent: str | None) -> str:
    """Build the synthesis instruction for `accent`."""
    _, description = ACCENTS[normalise(accent)]
    return f"Speak in {description}. {_TONE}"


def catalogue() -> list[dict[str, str]]:
    """Accents in a shape the frontend can render directly."""
    return [{"id": key, "label": label} for key, (label, _) in ACCENTS.items()]
