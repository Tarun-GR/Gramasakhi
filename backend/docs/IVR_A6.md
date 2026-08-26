# IVR-A6 — Security + Production Readiness

IVR-A6 hardens the existing A1–A5 telephony adapter for public/production deployment without changing RAG, STT, TTS, or Web/Android.

**LIVE TELEPHONY NOT TESTED** unless a real Exotel call was performed.

---

## 1. Threat model

| Threat | Mitigation |
|--------|------------|
| Unauthenticated webhook abuse | Optional operator shared secret; IP rate limits |
| CallSid flooding / session exhaustion | CallSid validation; session TTL; max active sessions |
| SSRF via RecordingUrl | HTTPS allowlist; private/metadata IP block; guarded redirects |
| Audio token scanning | Opaque tokens; TTL; single-use; rate limits on `/audio` |
| Cross-call state leakage | CallSid-scoped sessions; token bound to CallSid |
| Caller impersonation of account/conversation | Server-only bridge account; ignored body overrides |
| Secret leakage | No credentials in responses/logs; production config guard |
| Unbounded memory | Session + audio token caps; TTL purge |

---

## 2. Endpoint inventory

| Endpoint | Auth model | Notes |
|----------|------------|-------|
| `GET /api/ivr/language` | Provider boundary + optional secret | Creates session |
| `GET/POST /api/ivr/transcribe` | Active CallSid session | STT only |
| `POST /api/ivr/chat` | Active session + bridge account | RAG via server |
| `POST /api/ivr/tts` | Active session | Temp audio URL |
| `GET/HEAD /api/ivr/audio/{token}` | Opaque token only | No JWT |
| `GET/POST /api/ivr/continue` | Active session | DTMF loop |

---

## 3. Trust boundaries

**TRUSTED:** server session state, configured secrets, server `conversation_id`, generated audio tokens, `IVR_PUBLIC_BASE_URL`.

**UNTRUSTED:** `CallSid`, DTMF `digits`, `RecordingUrl`, caller phone fields, request headers/body overrides, Host header.

---

## 4. Provider authentication (Exotel)

**Audited:** Exotel Passthru/Gather callbacks pass query parameters via GET. Exotel docs recommend **IP allowlisting + HTTPS** for Passthru; they do **not** document HMAC signatures on Passthru/Gather URLs (unlike some Exotel CQA/ExoVerify webhooks).

**Implemented:** Optional operator-configured `IVR_WEBHOOK_SHARED_SECRET` (header `X-GramSakhi-Ivr-Secret` or query `ivr_secret`) — deployment hardening, **not** a native Exotel signature.

**Operator responsibility:** Restrict inbound traffic to Exotel IP ranges at firewall/load balancer.

---

## 5. CallSid validation

- Pattern: `^[A-Za-z0-9_-]{8,64}$`
- Rejects empty, oversize, control chars, path traversal
- Canonical form: stripped string via `normalize_call_sid()`

---

## 6. Session TTL + memory bounds

```env
IVR_SESSION_TTL_SECONDS=1800      # 30 min default
IVR_MAX_ACTIVE_SESSIONS=1000
```

- Activity refreshes TTL
- Expired → `410 Gone` or cleanup
- Capacity → `503` after purge of expired sessions

---

## 7. Audio token security

```env
IVR_AUDIO_TOKEN_TTL_SECONDS=300
IVR_MAX_ACTIVE_AUDIO_TOKENS=2000
```

- `secrets.token_urlsafe(32)` entropy
- Single-use GET; HEAD non-consuming
- Revoked on new TTS for same CallSid
- Invalid/expired/consumed → `404`

---

## 8. Public URL

- Built only from `IVR_PUBLIC_BASE_URL`
- Production requires HTTPS; blocks localhost/private IPs
- Startup guard fails if production config invalid

---

## 9. SSRF (RecordingUrl)

- HTTPS only (production)
- Host suffix allowlist (`.exotel.com`, `.exotel.in`, `.amazonaws.com`)
- Blocks localhost, loopback, RFC1918, link-local, `169.254.169.254`, `.internal`
- Blocks `file://`, `data://`
- Guarded redirect handler re-validates each hop
- Max URL length: `IVR_MAX_RECORDING_URL_LENGTH=2048`
- Response size + timeout limits (existing STT limits)

**TTS:** Returns binary MP3 only — no outbound TTS URL fetch.

---

## 10. Rate limiting (in-memory)

```env
IVR_RATE_LIMIT_WINDOW_SECONDS=60
IVR_RATE_LIMIT_PER_CALLSID=120
IVR_RATE_LIMIT_PER_IP=300
IVR_RATE_LIMIT_INVALID_PER_IP=60
IVR_RATE_LIMIT_AUDIO_PER_IP=120
```

Limitation: per-process only; multi-instance needs shared store for global limits.

---

## 11. Bridge account

- `IVR_CITIZEN_ACCOUNT_ID` (preferred) or `IVR_SYSTEM_ACCOUNT_PHONE`
- Caller cannot select account/conversation/language
- **Limitation:** all IVR callers share one bridge CitizenAccount until future identity work

---

## 12. Replay / concurrency

- A5 state machine + `turn_in_progress` flag
- Duplicate chat/TTS rejected with `409`
- Exotel HTTP retries may repeat idempotent steps — documented limitation

---

## 13. Logging / privacy

Allowed: masked CallSid prefix, state, latency, error category, turn count.

Not logged: raw transcript, full AI response, phone numbers, audio tokens, RecordingUrl, credentials.

---

## 14. Data retention

| Data | Retention |
|------|-----------|
| IVR session | TTL (`IVR_SESSION_TTL_SECONDS`) |
| STT temp recording | Deleted in `finally` (A2) |
| TTS temp audio | Single-use + TTL |
| Conversation (DB) | Existing app rules — unchanged |
| Permanent call recording | **Not implemented** |

---

## 15. Redis decision

**Decision: A — Keep in-memory for development/single-process; document Redis as production requirement for multi-worker/multi-instance.**

Evidence:
- Current store is process-local dict
- Restart clears sessions/tokens
- Horizontal scaling breaks CallSid affinity without shared storage
- Rate limits are per-process

**Redis NOT introduced in A6** — no proven single-host production deployment requiring it yet. A7 should validate operator topology before adding Redis.

---

## 16. Production configuration

Required when `APP_ENV=production`:

- `IVR_PUBLIC_BASE_URL` (HTTPS, public)
- `IVR_CITIZEN_ACCOUNT_ID` or `IVR_SYSTEM_ACCOUNT_PHONE`
- `OTP_DEV_RETRIEVAL_ENABLED=false`
- Recommended: `IVR_WEBHOOK_SHARED_SECRET`, Exotel IP allowlisting

---

## 17. Verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest tests.test_ivr_a6 -v
.\.venv\Scripts\python.exe scripts\ivr_a6_verify.py
```

---

## 18. Runtime validation

| Level | Status |
|-------|--------|
| STATICALLY VERIFIED | Yes |
| UNIT TESTED | Yes |
| ACTUAL PHONE TESTED | **NOT TESTED** |

---

## 19. A7 prerequisites

- Redis (or equivalent) for multi-instance session/token/rate-limit consistency
- Exotel IP allowlisting at edge
- Production TLS certificate on public API
- Live telephony smoke test
