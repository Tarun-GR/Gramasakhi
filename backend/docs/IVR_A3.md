# IVR-A3 — Chat / RAG Integration

IVR-A3 routes A2 transcriptions through the **existing** GramSakhi chat service (`handle_citizen_chat`) — same RAG, Evidence Validator, and Ollama path as `POST /api/chat`.

**Not included:** TTS, phone playback, Redis, new LLM/RAG, Web/Android changes.

**LIVE TELEPHONY NOT TESTED** unless a real Exotel call was performed.

---

## 1. Existing `/api/chat` contract (audited)

| Item | Value |
|------|-------|
| **HTTP endpoint** | `POST /api/chat` and `POST /api/chat/` |
| **Auth** | JWT Bearer — `get_current_citizen()` → `CitizenAccount` |
| **Request body** | `ChatRequest` |
| **Required** | `message` (1–8000 chars) |
| **Optional** | `conversation_id`, `language`, `stt_language`, `input_mode`, `voice_request_id` |
| **Conversation** | If `conversation_id` omitted → `create_conversation()`; else `get_owned_conversation()` |
| **Service entry** | `conversation_service.handle_citizen_chat(db, citizen, ...)` |
| **Pipeline** | rewrite → RAG (`answer_with_evidence_gate`) → eligibility/guidance/action-plan → store messages |
| **Response** | `ChatResponse` — `answer`, `sources`, `validated`, `confidence`, `response_language`, assistance metadata |
| **Evidence on messages** | `SUPPORTED` / `UNSUPPORTED` stored on assistant `Message.evidence_status` |
| **API evidence mapping** | Frontend maps `validated` + `live_status` → SUPPORTED / PARTIAL / UNSUPPORTED |
| **Errors** | `HTTPException` 400/401; unhandled → 503 generic message |
| **Timeout** | No explicit IVR timeout; RAG/live/Ollama use internal timeouts |

IVR-A3 calls **`handle_citizen_chat()` directly** (no HTTP loopback, no caller JWT).

---

## 2. Authorization model

`/api/chat` requires an authenticated `CitizenAccount`. IVR uses a **server-side bridge account**:

| Config | Purpose |
|--------|---------|
| `IVR_CITIZEN_ACCOUNT_ID` | Preferred — UUID of dedicated IVR CitizenAccount |
| `IVR_SYSTEM_ACCOUNT_PHONE` | Fallback lookup by phone number |

- Never exposed to caller
- Never accepts caller-supplied `account_id` / `citizen_id`
- All IVR conversations belong to this bridge account (isolated from mobile/web citizen sessions by CallSid → conversation mapping)

Seed a dedicated account in production; set one of the config values in `backend/.env`.

---

## 3. CallSid → conversation architecture

```
Call start (A1)
  → language stored on CallSid session
A2 STT
  → transcription stored on CallSid session
A3 POST /api/ivr/chat
  → resolve/create conversation_id on session (server-side)
  → handle_citizen_chat(..., conversation_id=session.conversation_id)
  → store returned conversation_id on session for reuse
Call end
  → session cleared on process restart (in-memory dev store)
```

- **One CallSid → one conversation** (reused on subsequent A3 calls)
- CallSid B never sees CallSid A's `conversation_id`
- Caller cannot supply `conversation_id`

Production multi-instance: shared session store (e.g. Redis) required.

---

## 4. Language flow

| A1 session | Passed to `handle_citizen_chat` |
|------------|----------------------------------|
| `kn` | `KN` (`language` + `stt_language`) |
| `hi` | `HI` |
| `en` | `EN` |

Request fields `language`, `lang`, `language_hint` are **ignored**.

---

## 5. API

### `POST /api/ivr/chat`

**Request:**
```json
{
  "CallSid": "CA…",
  "transcription": "What is PM-KISAN?"
}
```

`transcription` optional if A2 stored it on the session.

**Response:**
```json
{
  "call_sid": "CA…",
  "language": "en",
  "conversation_id": "…",
  "response_text": "…",
  "evidence_status": "SUPPORTED",
  "sources": […],
  "response_language": "EN",
  "success": true
}
```

**Errors:** 400 (CallSid/language/transcription); 503 (chat/auth failures). No stack traces or JWT in response.

---

## 6. Evidence handling

IVR `evidence_status` derived from chat result (same semantics as web adapter):

| Condition | Status |
|-----------|--------|
| `validated` + `llm_invoked` | SUPPORTED |
| `validated` (incl. `llm_unavailable`) | SUPPORTED |
| not validated + `live_status=FAILED` | UNSUPPORTED |
| not validated + sources present | PARTIAL |
| otherwise | UNSUPPORTED |

Sources passed through from chat result — never fabricated.

---

## 7. Privacy & security

- No raw transcription in logs
- Masked CallSid in logs only
- No JWT/credentials in response
- Ignored body fields: `conversation_id`, `account_id`, `citizen_id`, `language`, `lang`

---

## 8. Exotel Flow (after A2)

After STT success → HTTP POST to `/api/ivr/chat` with `CallSid` (transcription optional if already on session) → use `response_text` in a Say applet (A4 will add TTS).

---

## 9. Known limitations

- In-memory CallSid session (dev)
- Long responses not truncated (A4 TTS constraint documented)
- Single bridge account for all IVR calls
- **LIVE TELEPHONY NOT TESTED** in CI

---

## 10. Verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest tests.test_ivr_a3 -v
.\.venv\Scripts\python.exe scripts\ivr_a3_verify.py
```

OpenAPI: `/docs` → **ivr** → `POST /api/ivr/chat`
