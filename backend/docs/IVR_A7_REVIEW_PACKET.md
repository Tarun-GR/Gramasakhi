# IVR-A7 Independent Review Packet

This packet is for an adversarial reviewer. It contains no secrets.

---

## Architecture summary

GramSakhi IVR is an Exotel adapter over the existing citizen chat stack.

1. A1 stores language on an in-memory CallSid session.
2. A2 fetches an Exotel recording (SSRF-guarded) and runs existing STT.
3. A3 sends the session transcript through existing `handle_citizen_chat` using a server-configured bridge CitizenAccount.
4. A4 synthesizes the A3 text with existing TTS and issues a temporary audio token.
5. Exotel fetches `GET /api/ivr/audio/{token}`.
6. A5 offers continue/end DTMF and loops or terminates.

Redis is **not** in the stack. State dies on process restart.

---

## Endpoint inventory

See `backend/docs/IVR_A7.md` section 3. Routes live in `backend/app/api/endpoints/ivr.py` under prefix `/api/ivr`.

---

## Trust boundaries

Trusted: configured env, server session fields, issued tokens, `IVR_PUBLIC_BASE_URL`.

Untrusted: every provider/caller field (`CallSid`, `digits`, `RecordingUrl`, phones, body `language` / `conversation_id` / `account_id`, Host).

---

## State machine

`IvrCallState` in `backend/app/services/ivr/call_state.py`.

LANGUAGE_SELECTION → READY_FOR_INPUT → TRANSCRIBING → PROCESSING_CHAT → SYNTHESIZING → PLAYING_RESPONSE → ASK_CONTINUE → READY_FOR_INPUT | ENDING.

Concurrency: `turn_in_progress`. TTL: `IVR_SESSION_TTL_SECONDS`.

---

## Security controls

| Control | Location |
|---------|----------|
| CallSid validation | `call_sid_validation.py` |
| Guards / rate limits | `ivr_guard.py`, `ivr_rate_limit.py` |
| Webhook secret | `webhook_auth.py` |
| SSRF | `exotel_recording.py` |
| Public URL | `public_url.py` |
| Audio tokens | `audio_token_store.py` |
| Bridge account | `ivr_auth.py` |
| Prod config | `ivr_config.py`, `main.py` |

---

## Known limitations

- Single-process in-memory state
- Optional operator secret ≠ Exotel HMAC
- Shared bridge account
- Language endpoint can reset language later in the call
- `X-Forwarded-For` used for IP buckets
- Live Exotel/phone path not tested

---

## Production deployment assumptions

Supported model: **one backend process**, public HTTPS `IVR_PUBLIC_BASE_URL`, configured bridge account, edge IP allowlist for Exotel.

Not supported without Redis (or equivalent): multiple uvicorn workers or multiple instances.

---

## Test results

- A7: 41/41 PASS
- IVR A1–A7: 260/260 PASS
- Backend: 989/989 PASS
- Web build / mobile typecheck / Android export: PASS
- Release-gate script: PASS 6, FAIL 0, WARN 6 — GO WITH LIMITATIONS

---

## Independent reviewer instruction

```
You are an adversarial security/reliability reviewer.
Do not trust the implementation's existing audit reports.
Inspect actual code.
Find P0/P1/P2/P3/P4 issues.
Focus on SSRF, webhook authenticity, session isolation, replay,
race conditions, resource exhaustion, secrets, privacy, Exotel
contract assumptions, and production configuration.
Do not redesign RAG/LLM/STT/TTS.
For every finding provide file/function evidence.
```

No independent Grok review was performed as part of this packet's creation.
