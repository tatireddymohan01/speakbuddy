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
├── tests/                  Smoke tests (fake keys, stub provider — no real API calls)
├── .github/workflows/
│   └── ci-cd.yml           Lint + test on every PR; deploy to Azure on push to main
├── .env.example
├── requirements.txt
├── requirements-dev.txt    pytest + ruff (CI and local only)
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

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
python -m pytest
```

The tests use fake credentials and a stub provider, so they need no `.env` and
never call a real API.

---

## Deploying to Azure

[`.github/workflows/ci-cd.yml`](.github/workflows/ci-cd.yml) runs on GitHub Actions:

| Trigger | What runs |
| --- | --- |
| Pull request to `main` | Lint + tests. Nothing is deployed. |
| Push to `main` | Lint + tests → deploy to Azure App Service → wait for `/health` on the live site |
| **Run workflow** button | Same as a push, e.g. to redeploy on demand |

If lint or tests fail, the run stops before deploying and the live site keeps
the last good version. The deploy job is **skipped** until the one-time setup
below is done.

### One-time setup

Run these in **Azure Cloud Shell (Bash)** from the portal — it is already signed
in to the account you opened the portal with. `<app-name>` must be globally
unique; it becomes `https://<app-name>.azurewebsites.net`.

**1. Create the App Service** (Linux, Python 3.12; the Free F1 plan is enough to start)

```bash
az group create --name rg-speakbuddy-prod --location <region>
az appservice plan create --name asp-speakbuddy-prod --resource-group rg-speakbuddy-prod --sku F1 --is-linux
az webapp create --name <app-name> --resource-group rg-speakbuddy-prod --plan asp-speakbuddy-prod --runtime "PYTHON:3.12"
az webapp update --name <app-name> --resource-group rg-speakbuddy-prod --https-only true
```

**2. Add the app settings** in the portal: *App Service → Settings → Environment
variables*. Use the same variables as your `.env`, plus one more:

| Setting | Value | Why |
| --- | --- | --- |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` | Azure installs `requirements.txt` on each deploy |
| `LLM_PROVIDER` and that provider's key | e.g. `openai` + `OPENAI_API_KEY` | The app refuses to start without them |

Enter keys in the portal rather than with `az … --settings`, so they never land
in shell history. The pipeline never touches app settings, so keys never pass
through GitHub.

**3. Let GitHub Actions sign in to Azure** with OIDC — no password is stored anywhere.

```bash
APP_ID=$(az ad app create --display-name speakbuddy-github --query appId -o tsv)
az ad sp create --id $APP_ID

cat > credential.json <<'EOF'
{
  "name": "github-production",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:tatireddymohan01/speakbuddy:environment:production",
  "audiences": ["api://AzureADTokenExchange"]
}
EOF
az ad app federated-credential create --id $APP_ID --parameters credential.json

WEBAPP_ID=$(az webapp show --name <app-name> --resource-group rg-speakbuddy-prod --query id -o tsv)
az role assignment create --assignee $APP_ID --role "Website Contributor" --scope $WEBAPP_ID

echo "AZURE_CLIENT_ID=$APP_ID"
az account show --query "{AZURE_TENANT_ID:tenantId, AZURE_SUBSCRIPTION_ID:id}" -o yaml
```

The role is limited to this one web app. The `subject` must match exactly: the
deploy job runs in the GitHub environment named `production`.

**4. Add them to GitHub**: *repo → Settings → Secrets and variables → Actions*

| Name | Type | Value |
| --- | --- | --- |
| `AZURE_CLIENT_ID` | Secret | from step 3 |
| `AZURE_TENANT_ID` | Secret | from step 3 |
| `AZURE_SUBSCRIPTION_ID` | Secret | from step 3 |
| `AZURE_WEBAPP_NAME` | **Variable** | `<app-name>` — setting this switches the deploy job on |

Then open *Actions → CI/CD → Run workflow*, or push to `main`.

### Day to day

| Task | How |
| --- | --- |
| Ship a change | Push to `main` (or merge a PR) — tested and deployed automatically |
| Change a setting or rotate a key | Edit it under *Environment variables* in the portal; the app restarts itself |
| Roll back | `git revert <commit>` and push |

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
| Deploy job shows as skipped | The `AZURE_WEBAPP_NAME` repository variable isn't set yet |
| Azure login fails: *no matching federated identity record* | The credential `subject` must be exactly `repo:tatireddymohan01/speakbuddy:environment:production` |
| Deploy succeeds but the health check times out | Open *Log stream* in the portal — usually a missing provider key, or `SCM_DO_BUILD_DURING_DEPLOYMENT` not set |
