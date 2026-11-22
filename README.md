# SpeakBuddy 🗣️

An AI-assisted spoken English practice tutor. Talk to it out loud — it listens
continuously, replies in a natural voice, and can gently correct your English as
you go.

- **Backend** — FastAPI, with a swappable LLM provider (Anthropic, OpenAI, Azure OpenAI)
- **Frontend** — plain HTML/CSS/JS, responsive from ~320px phones up to large desktops
- **Keys never reach the browser** — the frontend only ever calls `POST /api/chat`
  on its own origin

---

## Quick start

```bash
# 1. From the project root, create and activate a virtual environment
python -m venv .venv

#    Windows (PowerShell)
.venv\Scripts\Activate.ps1
#    macOS / Linux
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your provider
cp .env.example .env        # Windows: copy .env.example .env
#    …then edit .env and set LLM_PROVIDER plus that provider's key

# 4. Run
uvicorn backend.main:app --host :: --port 8010 --reload
```

Open **<http://localhost:8010>**, press **Start**, allow the microphone, and
start talking.

> Use `localhost`, not a `file://` path — microphone access requires a secure
> context, and `http://localhost` counts as one.

### Why `--host ::` and port 8010?

Windows resolves `localhost` to IPv6 (`::1`) **before** IPv4. Two consequences:
>
> - **Port 8000 is a bad default here** — Docker Desktop / WSL commonly hold it
>   on IPv6, so the browser reaches Docker and gets its 404 while your server
>   sits unreached on IPv4.
> - **`--host ::` matters** — uvicorn's default binds IPv4 only, which
>   `localhost` never tries first.
>
> Check what owns a port before using it:
> `Get-NetTCPConnection -LocalPort 8010 -State Listen`

---

## Configuration

Everything lives in `.env` (gitignored). `.env.example` lists every variable.

| Variable | Purpose |
| --- | --- |
| `LLM_PROVIDER` | `anthropic`, `openai`, or `azure` |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | Anthropic credentials and model |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | OpenAI credentials and model |
| `AZURE_OPENAI_API_KEY` | Azure resource key |
| `AZURE_OPENAI_ENDPOINT` | e.g. `https://my-resource.openai.azure.com` |
| `AZURE_OPENAI_DEPLOYMENT` | Your deployment name (used in the URL) |
| `AZURE_OPENAI_API_VERSION` | e.g. `2024-10-21` |
| `MAX_TOKENS` | Reply length cap (default `400` — replies are spoken) |
| `REQUEST_TIMEOUT_SECONDS` | Upstream timeout (default `45`) |
| `MAX_HISTORY_MESSAGES` | Turns relayed upstream for continuity (default `20`) |
| `ALLOWED_ORIGINS` | Only needed if the frontend is served separately |

Only the selected provider's variables need values. **The app refuses to start**
if they are missing, and tells you exactly which ones:

```
Startup aborted — LLM_PROVIDER=azure requires these environment variables:
AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT
```

Switching providers is one line in `.env` plus a restart — no code changes.

---

## Project layout

```
.
├── backend/
│   ├── main.py             FastAPI app, routes, error handlers, static mount
│   ├── config.py           pydantic-settings configuration
│   ├── schemas.py          Request/response models
│   ├── prompts.py          Tutor system prompts (casual / lesson)
│   └── providers/
│       ├── __init__.py     Registry — discovers provider modules dynamically
│       ├── base.py         HTTP transport, timeouts, safe error mapping
│       ├── _openai_compat.py   Shared chat-completions helpers
│       ├── anthropic.py    Anthropic Messages API
│       ├── openai.py       OpenAI Chat Completions
│       └── azure.py        Azure OpenAI Service
├── frontend/
│   ├── index.html
│   ├── styles.css          Mobile-first, breakpoints at 480/768/1024/1280px
│   └── app.js              Speech recognition, TTS, chat, state machine
├── .env.example
├── requirements.txt
└── README.md
```

---

## API

### `GET /health`

```json
{ "status": "ok", "provider_configured": "true" }
```

Deliberately does **not** report which provider is active.

### `POST /api/chat`

```jsonc
// Request
{
  "messages": [
    { "role": "assistant", "content": "Hi! I'm SpeakBuddy…" },
    { "role": "user",      "content": "I go to market yesterday" }
  ],
  "mode": "lesson"          // "casual" | "lesson" | "correction"
}

// 200 OK
{ "reply": "Nice! Small thing — we'd say…", "mode": "lesson" }

// Error (4xx / 5xx)
{ "error": "Anthropic is rate limiting requests right now. Wait a moment and try again.",
  "retryable": true }
```

The final message must have `role: "user"`. The system prompt is built
server-side from `mode`; the client cannot influence it beyond that choice.

---

## Adding a fourth provider

Providers are discovered by scanning `backend/providers/`, so adding one means
**adding one file** — nothing else changes.

Create `backend/providers/yourprovider.py`:

```python
from ..config import get_settings
from .base import post_json

REQUIRED_SETTINGS = ("yourprovider_api_key",)   # validated at startup

async def get_reply(messages: list[dict], system_prompt: str) -> str:
    settings = get_settings()
    body = await post_json(
        "https://api.example.com/v1/chat",
        {"Authorization": f"Bearer {settings.yourprovider_api_key}"},
        {"messages": messages, "system": system_prompt},
        provider="yourprovider",
    )
    return body["reply"]
```

Add the matching fields to `Settings` in `config.py`, then set
`LLM_PROVIDER=yourprovider`. If it speaks the OpenAI chat-completions format,
import `build_messages` / `parse_reply` from `._openai_compat` and the module is
about ten lines.

---

## Browser support

Voice input uses the **Web Speech API**, which in practice means Chromium:

| Browser | Speech input | Speech output |
| --- | --- | --- |
| Chrome / Edge (desktop) | ✅ | ✅ |
| Chrome (Android) | ✅ | ✅ |
| Safari (macOS / iOS) | ⚠️ partial | ✅ |
| Firefox | ❌ | ✅ |

Where recognition is unavailable or the microphone is denied, the app says so
plainly and the typed-input box keeps it usable.

---

## Practice modes

Chosen in the header, sent with every request. The system prompt is built
server-side from this value.

| Mode | Behaviour |
| --- | --- |
| **Casual Chat** | Ordinary conversation. Never corrects — it just talks with you. |
| **Lesson Mode** | Chats normally, but gently fixes the single most important mistake per turn, inline. |
| **Speech Correction** | Full coaching every turn — what was wrong, the rule behind it, and why the fix helps. |

Speech Correction analyses tense, agreement, articles, prepositions, plurals,
word order and word choice, plus any mispronunciation the transcript spelling
gives away. Labels are highlighted in the transcript:

```
You said:        Yesterday I go to market and buy two bread for my family
Better:          Yesterday I went to the market and bought two loaves of bread…
Grammar:         Use the past simple for actions done in the past: "went", "bought"
Word choice:     "Loaves of bread" is the right term for countable bread.
Why it matters:  The right tense and words make your story clear and natural.
Practice:        I went to the store and bought some milk.
Try:             What else did you do at the market?
```

`Grammar`, `Word choice` and `Pronunciation` appear only when there is a real
issue of that kind — at most three per turn. Pronunciation is raised only when
the transcript itself is evidence (a word arriving as a *different real word*,
like "wery" for "very"), since the model cannot hear audio.

When the sentence was already correct it switches to a praise shape — `Great:`
naming what they handled well, then `Level up:` with a more idiomatic
alternative — rather than inventing a mistake.

**Only part of it is spoken.** Reading the whole analysis aloud would be
tedious, so the voice gets `Better`, `Practice` and `Try` (about 12 seconds);
the full breakdown stays on screen to read.

## How the voice loop works

1. **Listening** — recognition runs continuously with interim results.
2. A **~1.7s silence** (or the engine's `speechend`, which is faster) ends the
   turn and sends it automatically. No button press.
3. **Thinking** — the mic stops while the request is in flight.
4. **Speaking** — the reply is spoken; the mic stays off so the tutor never
   hears itself.
5. Recognition resumes the moment speech output finishes.

The status pill shows which of those four states you're in at all times, and the
mic button pauses the whole loop.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Startup aborted — LLM_PROVIDER=… requires…` | Fill those variables in `.env` |
| Mic button disabled | Browser lacks the Web Speech API — use Chrome or Edge |
| "Microphone blocked" | Allow the mic via the icon in the address bar, then press Start |
| Azure calls fail | Check `AZURE_OPENAI_DEPLOYMENT` is the *deployment* name, and that the endpoint has no trailing slash |
| Tutor replies get cut off | Raise `MAX_TOKENS` in `.env` |
| Server logs a 401 from the provider | The API key was rejected — check `.env` and restart |
