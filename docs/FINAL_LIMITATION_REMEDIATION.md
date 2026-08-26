# FINAL LIMITATION REMEDIATION REPORT

One controlled pass across Web + Android + IVR. Only verified code-level
limitations were fixed. No new product features, no architecture redesign,
no Redis, no Exotel deployment, no RAG/STT/TTS replacement.

Date: 2026-08-26

---

## 1. Scope

| System | Source of findings | What was in scope |
|--------|--------------------|-------------------|
| Web | W1 release gate + live frontend/backend audit | Auth/session, OTP, source-link safety, markdown, error leakage, `/docs`, conversation isolation |
| Android | A1–A5 documented limitations + live mobile audit | Production API URL, UI i18n, `low_confidence`, error sanitization, voice cache, gate harnesses |
| IVR | A7 known limitations + live IVR code | XFF, `/language` re-entry, direct upload, CallSid privacy, TTL alias, webhook secret, cleanup |

---

## 2. Findings verified

| System | Finding | Severity | Decision |
|--------|---------|----------|----------|
| IVR | `X-Forwarded-For` trusted for IP rate limiting | P2 | **Fixed** — untrusted unless `IVR_TRUST_PROXY_HEADERS=true` |
| IVR | `/language` could reset language mid-turn | P2 | **Fixed** — only `LANGUAGE_SELECTION` / `READY_FOR_INPUT` |
| IVR | `POST /api/ivr/transcribe` reachable in production | P2 | **Fixed** — 404 in production unless explicitly enabled |
| IVR | Full CallSid logged | P3 | **Fixed** — `mask_call_sid` used consistently |
| IVR | Audio-token TTL env-name mismatch | P3 | **Fixed** — `IVR_PUBLIC_AUDIO_TOKEN_TTL` alias |
| IVR | Webhook secret accepted via query string | P3 | **Fixed** — header preferred; query disableable |
| IVR | `terminate_ivr_session` created a session while cleaning | P3 | **Fixed** — `peek_session` |
| IVR | In-memory sessions/tokens/rate limits | P2 | **Not fixed** — Redis is a deployment decision |
| IVR | No native Exotel HMAC | P2 | **Not fixed** — no HMAC contract exists |
| IVR | Shared bridge CitizenAccount | P2 | **Not fixed** — callers cannot override account; identity redesign out of scope |
| Android | Production builds fall back to `http://10.0.2.2:8000` | P0 | **Fixed** — `__DEV__` guard + refuse emulator hosts |
| Android | UI chrome hardcoded English | P2 | **Fixed** — 82-key kn/hi/en string table |
| Android | `low_confidence` typed but ignored | P2 | **Fixed** — composer review, no auto-send |
| Android | `parseApiDetail` forwarded raw backend `detail` | P2 | **Fixed** — sanitizer |
| Android | Stale TTS cache files after crash | P3 | **Fixed** — startup sweep |
| Android | A1/A2 stderr treated as failure | — | **Not present** — already exit-code based |
| Android | Cached auth kept on network error | P3 | **Not fixed** — intentional offline resilience; 401/403 still clears |
| Web | Eligibility/guidance links skipped `safeHttpUrl` | P2 | **Fixed** |
| Web | `/docs` + OpenAPI always exposed | P3 | **Fixed** — disabled when `APP_ENV=production` |
| Web | Phone number in verify-otp / register query string | P4 | **Fixed** — navigation state + `tempPhone` |
| Web | Raw `detail` echoed in toasts / chat errors | P4 | **Fixed** — citizen-safe filter |
| Web | `console.error(err)` on forgot-password | P4 | **Fixed** |
| Web | JWT in `localStorage` | P3 | **Not fixed** — HttpOnly cookie is an architecture change |
| Web | Default API URL / CORS localhost | P3 | **Not fixed** — operator must set `VITE_API_BASE_URL` at build (documented W1 limitation) |

---

## 3. Fixes

| System | File | Fix | Reason |
|--------|------|-----|--------|
| IVR | `backend/app/services/ivr/ivr_guard.py` | XFF only when `IVR_TRUST_PROXY_HEADERS` | Stop client-spoofed rate-limit bypass |
| IVR | `backend/app/services/ivr/language_flow.py` | Block language re-entry mid-turn | Preserve A5 state machine |
| IVR | `backend/app/api/endpoints/ivr.py` | Production 404 on direct upload; masked CallSid; guard-normalized CallSid | Shrink attack surface; privacy |
| IVR | `backend/app/services/ivr/webhook_auth.py` | Query-secret gated by `IVR_WEBHOOK_SECRET_ALLOW_QUERY` | Prefer header; avoid proxy logs |
| IVR | `backend/app/services/ivr/call_sid_validation.py` | Shared `mask_call_sid` | Consistent privacy |
| IVR | `backend/app/services/ivr/audio_token_store.py` | Spec-name TTL alias | Config naming without breaking deploys |
| IVR | `backend/app/services/ivr/language_session.py` | `peek_session` | Cleanup without create |
| IVR | `backend/app/services/ivr/session_cleanup.py` | Use `peek_session` | Same |
| IVR | `backend/app/core/config.py`, `.env.example` | New IVR settings with safe defaults | Operator control |
| IVR | `backend/tests/test_ivr_a7.py` | +8 regression tests | Lock the fixes |
| Android | `mobile/src/api/config.ts` | No emulator fallback / host in production | P0 production URL |
| Android | `mobile/src/utils/errors.ts` | Sanitize `parseApiDetail` | Citizen-safe errors |
| Android | `mobile/src/hooks/useVoiceInput.ts`, `app/chat.tsx` | `onLowConfidence` → composer | Supported backend contract |
| Android | `mobile/src/api/voice.ts`, `TtsPlaybackContext.tsx` | Sweep `gramsakhi-tts-*` on start | Privacy leftover files |
| Android | `mobile/src/i18n/strings.ts` + LanguageContext + screens | kn/hi/en UI chrome | Documented localization gap |
| Android | `mobile/scripts/a1_regression_verify.mjs` | ErrorBoundary check accepts i18n | Gate false-fail |
| Android | `mobile/scripts/a4_regression_verify.mjs`, `a5_release_gate.mjs` | i18n tables ≠ translation service | Gate false-fail |
| Android | `mobile/README.md` | Production URL enforcement | Document |
| Web | `EligibilityGuidancePanel.jsx` | All hrefs through `safeHttpUrl` | javascript:/data: blocked |
| Web | `backend/app/main.py` | Disable docs/openapi/redoc in production | Debug surface |
| Web | `LoginForm.jsx`, `OTPVerification.jsx`, `RegisterForm.jsx` | Phone not in URL | History / log privacy |
| Web | `chat-store.js`, `services/api.js` | Citizen-safe error filter | Internal-detail leakage |
| Web | `ForgotPassword.jsx` | Drop `console.error(err)` | Phone/detail in DevTools |
| Web | `w1_release_gate.mjs` | Eligibility-link check | Regression lock |
| Web | `backend/tests/test_h7c_production_readiness.py` | Docs-off-in-prod source + /docs-in-dev | Regression lock |

---

## 4. Findings intentionally not fixed

| Finding | Why not this pass |
|---------|-------------------|
| IVR in-memory state | Adding Redis is a deployment/architecture change explicitly forbidden. Single-process remains supported. Multi-instance **requires Redis**. |
| No Exotel HMAC | There is no documented HMAC contract to implement. Current protection is shared secret + operator IP allowlist. |
| Shared IVR CitizenAccount | Callers cannot supply an account or conversation ID (`get_ivr_citizen` is server-config only). Per-caller identity is a product redesign. |
| JWT in `localStorage` | Moving to HttpOnly cookies changes the auth architecture for Web + Android. XSS-stealable remains a residual risk; existing XSS controls (no raw HTML, `safeHttpUrl`) mitigate. |
| Default Web API URL `http://127.0.0.1:8000` | W1 already records this as a build-time operator responsibility. Inventing a production URL would be worse. |
| Cached Android session on network error | Intentional offline resilience. 401/403 still clears the session. An auth bypass was not found. |
| A1/A2 stderr-as-failure | **Does not exist.** `runCmd` fails only on non-zero exit. |
| Live Exotel / device microphone / real-browser isolation | Not performed; cannot be claimed. |

---

## 5. Regression

Exact results from this pass (not reused from A7):

### Backend

| Suite | Result |
|-------|--------|
| Full backend | **999/999 PASS** |
| `test_h7c_production_readiness` (incl. new docs tests) | **4/4 PASS** |

### IVR

| Suite | Result |
|-------|--------|
| A1 | 21/21 |
| A2 | 36/36 |
| A3 | 36/36 |
| A4 | 39/39 |
| A5 | 28/28 |
| A6 | 59/59 |
| A7 | 49/49 |
| IVR total | **268/268 PASS** |
| `ivr_a7_release_gate.py` | EXIT 0, GO WITH LIMITATIONS |

### Web

| Check | Result |
|-------|--------|
| `npm run build` | PASS |
| `w1_release_gate.mjs` | **52 checks, 0 failures, PASS** |

### Android

| Check | Result |
|-------|--------|
| `npx tsc --noEmit` | PASS |
| `npx expo export --platform android` | PASS |
| A1 regression | **60 checks, 0 failures, PASS** |
| A2 regression | **39 checks, 0 failures, PASS WITH LIMITATIONS** |
| A3 regression | **46 checks, 0 failures, PASS WITH LIMITATIONS** |
| A4 regression | **50 checks, 0 failures, PASS WITH LIMITATIONS** |
| A5 release gate | **52 checks, 0 failures, PASS** |

No device, emulator-hardware, or live telephony testing was performed.

---

## 6. Remaining limitations

### Code limitations

- JWT remains in `localStorage` (Web) / SecureStore (Android). Web XSS can still steal the token if a new XSS is introduced.
- Web default API origin is localhost unless `VITE_API_BASE_URL` is set at build time.
- IVR callers share one configured CitizenAccount (no per-caller identity).
- Voice temp-file delete is best-effort (process kill mid-record can still leave a file until next sweep / OS cache eviction).

### Deployment limitations

- IVR in-memory state: **single-process only**. Multi-instance requires Redis (or equivalent shared store).
- IVR webhook authenticity: shared secret + edge IP allowlist. No native Exotel HMAC.
- Production must set: `APP_ENV=production`, `IVR_PUBLIC_BASE_URL` (HTTPS, public), `IVR_CITIZEN_ACCOUNT_ID` or `IVR_SYSTEM_ACCOUNT_PHONE`, and preferably `IVR_WEBHOOK_SHARED_SECRET` with `IVR_WEBHOOK_SECRET_ALLOW_QUERY=false`.
- Production Android builds **must** set `EXPO_PUBLIC_API_BASE_URL` to an HTTPS origin (enforced at runtime).
- Production Web builds **must** set `VITE_API_BASE_URL`.
- CORS origins are still the local Vite ports; production origins are an operator config change.

### Device / runtime limitations

- Browser / device microphone and speaker hardware not tested.
- Cross-user concurrent session isolation on real browsers not tested.
- Android voice permission / background-kill paths not tested on device.
- Offline-kept JWT is used until the next online 401/403.

### Telephony limitations

- No live Exotel inbound call was placed.
- Provider playback failure remains not fully observable from the backend.
- DTMF / speech / public-audio-URL reachability from Exotel is untested.

---

## 7. Integrity

Unchanged in this pass (not modified):

- RAG pipeline
- FAISS
- BM25
- CrossEncoder
- Evidence Validator
- Ollama
- Eligibility evaluation / questioning / explanation
- Scheme guidance
- Action plan
- STT core (`stt_service`)
- TTS core (`tts_service`)
- Database schema / migrations

Touched only at the IVR adapter / web / mobile boundary: language session, webhook auth, public URL/rate-limit config, chat-store error filter, mobile API config and UI strings.

---

## 8. Final status

**LIMITATIONS REMAIN**

No remaining P0/P1/P2 *code* issue that this pass could safely remove.
What remains is external: deployment (Redis, Exotel HMAC/IP allowlist, production URL env vars), device/runtime, and live telephony.
)
