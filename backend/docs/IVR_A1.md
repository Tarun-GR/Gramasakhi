# IVR-A1 — Exotel inbound language selection

IVR-A1 implements a thin telephony adapter: Exotel Gather → GramSakhi language menu → DTMF → in-memory session by `CallSid` → confirmation → end.

**Not included in A1:** STT, TTS backend, `/api/chat`, RAG, recording, Redis.

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/ivr/language` | Exotel Gather Application URL |

### Query parameters (Exotel)

| Parameter | Required | Description |
|-----------|----------|-------------|
| `CallSid` | Yes | Call/session identifier |
| `digits` | No | DTMF input (`1`/`2`/`3`; may be quoted) |
| `CallFrom`, `From` | No | Caller (logged masked only) |
| `CallTo`, `To` | No | Called number |

### DTMF mapping

| Key | Language |
|-----|----------|
| 1 | Kannada (`kn`) |
| 2 | Hindi (`hi`) |
| 3 | English (`en`) |

### Responses

Always `HTTP 200` + `application/json` Gather object on success paths. `400` when `CallSid` is missing/blank.

## Exotel Flow configuration (dashboard)

Configure an Exotel Flow on your inbound number:

1. **Greeting** (optional static Say) — short welcome if desired; the application URL also plays the menu.
2. **Gather** applet
   - Application URL: `https://<your-api-host>/api/ivr/language?CallSid={CallSid}&CallFrom={CallFrom}&digits={digits}`
   - Method: GET
   - On input / timeout: point back to the same URL (Exotel passes `digits` when present).
3. **Branch on application response text** (recommended):
   - If response contains `"selected."` → **Hangup** (confirmation played).
   - If response contains `"Goodbye."` → **Hangup**.
   - Otherwise → loop Gather (menu or retry).
4. **Do not** enable call recording in A1 unless separately approved.

Until a real Exotel number and Flow are configured and dialed, telephony is **not** validated — only unit/static contract tests apply.

## Session storage (development)

- In-memory dict keyed by `CallSid` (`app/services/ivr/language_session.py`).
- **Process restart** clears active sessions.
- **Multiple API instances** need shared storage (e.g. Redis) for production.

## Configuration

Optional placeholders in `backend/.env` (never commit real values):

```
EXOTEL_ACCOUNT_SID=
EXOTEL_API_KEY=
EXOTEL_API_TOKEN=
```

Credentials are for Exotel dashboard/API tooling; they are **not** returned in IVR JSON responses.

## Verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest tests.test_ivr_a1 -v
.\.venv\Scripts\python.exe scripts\ivr_a1_verify.py
```

OpenAPI: `http://127.0.0.1:8000/docs` → tag **ivr**.
