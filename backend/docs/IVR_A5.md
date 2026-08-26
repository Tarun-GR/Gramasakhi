# IVR-A5 — Multi-Turn Conversational Loop

IVR-A5 loops A2→A3→A4 with a continue/end DTMF menu, preserving one `conversation_id` per `CallSid`.

**LIVE TELEPHONY NOT TESTED** unless a real Exotel call completed multiple turns.

---

## 1. Pre-A5 audit (A1–A4)

| Item | Pre-A5 behavior |
|------|-----------------|
| Session store | In-memory `IvrCallSession` keyed by `CallSid` |
| Fields | `language`, `transcription`, `conversation_id`, `last_response_text`, STT retry counters |
| `conversation_id` | Created on first successful A3 chat; reused via `store.get_conversation_id()` |
| `last_response_text` | Set by `chat_adapter` after successful chat |
| Audio tokens | Opaque single-use MP3 via A4 `audio_token_store` |
| Session clear | Only explicit `clear_session()` — **not** called after one turn pre-A5 |
| Post-playback | Exotel Flow hung up (one-turn) |

---

## 2. State machine

| State | Meaning |
|-------|---------|
| `LANGUAGE_SELECTION` | Initial / A1 menu |
| `READY_FOR_INPUT` | Awaiting caller speech |
| `TRANSCRIBING` | STT in progress / transcript ready for chat |
| `PROCESSING_CHAT` | Chat/RAG in progress |
| `SYNTHESIZING` | TTS pending/in progress |
| `PLAYING_RESPONSE` | Audio URL issued; Exotel playing |
| `ASK_CONTINUE` | Continue/end DTMF menu |
| `ENDING` | Call teardown |
| `ERROR` | Reserved for fatal categories |

### Transitions

```
LANGUAGE_SELECTION → (A1 digit) → READY_FOR_INPUT
READY_FOR_INPUT → (audio) → TRANSCRIBING
TRANSCRIBING → (A3 chat start) → PROCESSING_CHAT
PROCESSING_CHAT → (chat ok) → SYNTHESIZING
SYNTHESIZING → (A4 TTS ok) → PLAYING_RESPONSE
PLAYING_RESPONSE → (GET /continue) → ASK_CONTINUE
ASK_CONTINUE → 1 → READY_FOR_INPUT
ASK_CONTINUE → 2 → ENDING (session cleared)
```

Failures return to `READY_FOR_INPUT` with bounded retries, or `ENDING` after limits.

---

## 3. Same conversation

- `CallSid` → one `conversation_id` for all turns
- `handle_citizen_chat(..., conversation_id=store.get_conversation_id())`
- Turn counter increments **once per successful chat only**

---

## 4. Language persistence

- A1 language (`kn`/`hi`/`en`) remains authoritative
- STT → KN/HI/EN, Chat → KN/HI/EN, TTS → KN/HI/EN
- Request-body language/conversation overrides **ignored**

---

## 5. Turn limit

```env
IVR_MAX_TURNS=10   # default in settings
```

When limit reached, continue digit `1` returns goodbye and clears session.

---

## 6. Continue/end menu

**Endpoints:** `GET /api/ivr/continue`, `POST /api/ivr/continue`

| DTMF | Action |
|------|--------|
| 1 | Next question → `READY_FOR_INPUT` |
| 2 | Goodbye → `ENDING`, session cleanup |

Bounded invalid/no-input retries (`MAX_CONTINUE_RETRY_ATTEMPTS`).

---

## 7. Retry policies

| Failure | Policy |
|---------|--------|
| Silence (no recording) | 1 retry prompt, then goodbye |
| STT | `MAX_STT_RETRY_ATTEMPTS` (A2) |
| Chat | `MAX_CHAT_RETRY_ATTEMPTS` — no auto re-chat |
| TTS | `MAX_TTS_RETRY_ATTEMPTS` — no re-chat |

---

## 8. Concurrency

- `turn_in_progress` flag per `CallSid`
- Overlapping STT/chat/TTS → deterministic busy/`409` on chat/TTS state errors
- Different `CallSid` values are independent

---

## 9. Audio token lifecycle (A4 preserved)

- New TTS revokes prior token for same `CallSid`
- Single-use GET, TTL expiry, cleanup on session end

---

## 10. Exotel Flow (multi-turn)

1. A1 language Gather  
2. Loop: Record → `/transcribe` → `/chat` → `/tts` → Play audio  
3. `/continue` Gather (1=loop to step 2, 2=Hangup)  

Playback failure is **provider-side** — backend cannot observe Exotel fetch/play errors unless Exotel documents a callback (not implemented).

---

## 11. Configuration

```env
IVR_MAX_TURNS=10
IVR_PUBLIC_BASE_URL=https://api.example.in
```

---

## 12. Verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest tests.test_ivr_a5 -v
.\.venv\Scripts\python.exe scripts\ivr_a5_verify.py
```

---

## 13. Runtime validation

| Level | Status |
|-------|--------|
| STATICALLY VERIFIED | Yes |
| UNIT TESTED | Yes |
| ACTUAL PHONE TESTED | **NOT TESTED** |

---

## 14. Known limitations

- In-memory session/state (Redis required for multi-instance production)
- No Exotel playback acknowledgement callback
- Exotel may retry HTTP callbacks — duplicate STT/chat guarded by state machine but not full distributed idempotency
