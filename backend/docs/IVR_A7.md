# IVR-A7 — Final Release Gate

A7 is a release gate, not a feature sprint. It decides whether the existing A1–A6 IVR stack can be promoted to a **release candidate**.

**LIVE TELEPHONY NOT TESTED.** Do not treat unit-test success as proof that an Exotel phone call works.

---

## 1. Release scope

In scope: audit, tests, documentation, and one P2 reliability fix (bounded in-memory rate-limit keys).

Out of scope: RAG, FAISS, BM25, CrossEncoder, Evidence Validator, Ollama, eligibility, guidance, action plan, STT/TTS cores, Web, Android, Exotel provisioning, Redis deployment, DNS, cloud.

---

## 2. Complete architecture

```
Exotel Gather/Passthru
  → GET /api/ivr/language          (A1 language DTMF)
  → GET /api/ivr/transcribe        (A2 RecordingUrl → existing STT)
  → POST /api/ivr/chat             (A3 session transcript → existing chat/RAG)
  → POST /api/ivr/tts              (A4 session text → existing TTS → temp MP3 URL)
  → GET /api/ivr/audio/{token}     (Exotel fetches MP3)
  → GET /api/ivr/continue          (A5 DTMF continue/end)
```

State is process-local, keyed by validated `CallSid`. Chat uses a server-configured bridge CitizenAccount.

---

## 3. Endpoint inventory

| Endpoint | Purpose | Auth / trust | Session | Production-safe? |
|----------|---------|--------------|---------|------------------|
| `GET /api/ivr/language` | Language menu | Optional webhook secret + IP rate limit | Creates session | Yes, with operator IP allowlist |
| `GET /api/ivr/transcribe` | Exotel RecordingUrl STT | Active session | Required | Yes, SSRF-guarded |
| `POST /api/ivr/transcribe` | Direct audio upload | Active session | Required | Reachable in production (not APP_ENV-gated); treat as operator-restricted |
| `POST /api/ivr/chat` | RAG via bridge account | Active session | Required; TRANSCRIBING | Yes; caller cannot select account/conversation |
| `POST /api/ivr/tts` | TTS URL for playback | Active session | Required; SYNTHESIZING | Yes if `IVR_PUBLIC_BASE_URL` valid |
| `GET /api/ivr/audio/{token}` | Single-use MP3 | Opaque token + audio rate limit | Token-bound | Yes |
| `HEAD /api/ivr/audio/{token}` | Existence/length | Opaque token | Token-bound, non-consuming | Yes |
| `GET/POST /api/ivr/continue` | Continue/end | Active session | ASK_CONTINUE / PLAYING_RESPONSE | Yes |

No additional IVR routes are registered.

---

## 4. Security controls

- CallSid: `^[A-Za-z0-9_-]{8,64}$`
- Session TTL + max active sessions
- Audio tokens: high-entropy, TTL, single-use GET, max tokens
- RecordingUrl SSRF + redirect revalidation
- Public URL from config only (production HTTPS)
- In-memory rate limits (now key-capped)
- Optional `IVR_WEBHOOK_SHARED_SECRET`
- Production startup config guard

---

## 5. Trust boundaries

**Trusted:** server session, configured secrets, `IVR_PUBLIC_BASE_URL`, server `conversation_id`, issued audio tokens.

**Untrusted:** CallSid, digits, RecordingUrl, caller phone, headers, query, body overrides, Host header.

---

## 6. State machine

```
LANGUAGE_SELECTION → READY_FOR_INPUT → TRANSCRIBING → PROCESSING_CHAT
  → SYNTHESIZING → PLAYING_RESPONSE → ASK_CONTINUE
ASK_CONTINUE → READY_FOR_INPUT | ENDING
```

Invalid transitions raise `StateTransitionError`. Concurrent turns use `turn_in_progress`. Expired sessions return 410.

**Observed gap (P3):** `GET /language` can re-select language and force `READY_FOR_INPUT` from later states.

---

## 7. Deployment model

| Model | Status |
|-------|--------|
| A — single backend process | **SUPPORTED** |
| B — multiple workers on one machine | **NOT SUPPORTED** without shared state |
| C — multiple backend instances | **REQUIRES REDIS** (or equivalent) |

---

## 8. Redis requirement

**Decision: do not add Redis in A7.**

Redis is required only for models B/C. The tested deployment model is **A (single process)**. Restart clears sessions/tokens/rate limits.

---

## 9. Exotel assumptions

Documented in project IVR docs / source only. **NOT LIVE VERIFIED:**

- Gather `digits` / `CallSid` query shape
- Voicemail `RecordingUrl` host suffixes
- Exotel fetching `audio_url` (GET vs HEAD)
- retries, timeouts, hangup after goodbye
- playback success/failure observability

---

## 10. Production configuration

**REQUIRED PRODUCTION:** `APP_ENV=production`, `IVR_PUBLIC_BASE_URL` (HTTPS, public), `IVR_CITIZEN_ACCOUNT_ID` or `IVR_SYSTEM_ACCOUNT_PHONE`.

**OPTIONAL PRODUCTION:** `IVR_WEBHOOK_SHARED_SECRET`, rate-limit numbers, TTL/caps.

**DEVELOPMENT ONLY:** `OTP_DEV_RETRIEVAL_*`, `POST /api/ivr/transcribe` as a convenience path, HTTP localhost public URL.

**SAFE DEFAULTS:** session TTL 1800s, 1000 sessions, 2000 tokens, 10 turns, rate-limit key cap 4096.

Production must not silently invent a public URL or bridge account.

---

## 11. Regression results

| Suite | Result |
|-------|--------|
| A1 | 21/21 |
| A2 | 36/36 |
| A3 | 36/36 |
| A4 | 39/39 |
| A5 | 28/28 |
| A6 | 59/59 |
| A7 | 49/49 |
| IVR total | 268/268 |
| Backend | 999/999 |
| Web build | PASS |
| Mobile typecheck | PASS |
| Android export | PASS |
| `ivr_a7_release_gate.py` | PASS 6 / FAIL 0 / WARN 6 |

---

## 12. Known limitations

- In-memory session/token/rate-limit state (Redis required for multi-instance)
- No native Exotel HMAC on Passthru/Gather (shared secret + operator IP allowlist)
- Shared bridge CitizenAccount (callers are not individually identified)
- Provider playback failure not fully observable
- Live phone flow not tested

### Remediated in final limitation pass (Aug 2026)

- `X-Forwarded-For` is no longer trusted by default; enable `IVR_TRUST_PROXY_HEADERS=true` only behind a trusted reverse proxy.
- `/language` re-entry from an active turn state is blocked; language can only be (re)selected in `LANGUAGE_SELECTION`/`READY_FOR_INPUT`.
- `POST /api/ivr/transcribe` (direct upload) returns 404 in production unless `IVR_DIRECT_UPLOAD_IN_PRODUCTION=true`.
- Full CallSid values are no longer logged anywhere; masking is consistent.
- `IVR_PUBLIC_AUDIO_TOKEN_TTL` added as the spec-name alias for `IVR_AUDIO_TOKEN_TTL_SECONDS` (legacy name still honored).
- Webhook secret via query string can be disabled (`IVR_WEBHOOK_SECRET_ALLOW_QUERY=false`); header `X-GramSakhi-Ivr-Secret` is preferred.
- `terminate_ivr_session` no longer creates a session while cleaning up (`peek_session`).
- Upload STT path uses the guard-normalized CallSid.

---

## 13. Live-testing requirements (before production traffic)

1. Real Exotel inbound call
2. DTMF 1/2/3 language
3. Speech → STT → chat → TTS playback
4. Continue and hangup
5. Confirm Exotel can GET the public audio URL
6. Confirm operator IP allowlist + webhook secret

---

## 14. Final decision

**GO WITH LIMITATIONS** for a single-process release candidate, provided operator IP allowlisting (and preferably webhook secret) is applied before public exposure.

Do not promote models B/C without shared state.
