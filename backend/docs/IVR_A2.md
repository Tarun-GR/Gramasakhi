# IVR-A2 — Speech-to-Text Integration

IVR-A2 adds caller speech → existing GramSakhi STT → transcription stored on the CallSid session. **No `/api/chat`, RAG, TTS, or new STT model.**

**LIVE TELEPHONY NOT TESTED** unless a real Exotel number and Flow were dialed.

---

## 1. Existing STT contract (audited from codebase)

| Item | Value |
|------|-------|
| **HTTP endpoint** | `POST /api/chat/voice/transcribe` |
| **Method** | POST |
| **Content-Type** | `multipart/form-data` |
| **Multipart field** | `audio` (`UploadFile`, required) |
| **Language hint field** | `language_hint` (optional form field, `EN` / `KN` / `HI`) |
| **Authentication** | JWT Bearer (`HTTPBearer`) — citizen account required |
| **Accepted formats** | wav, webm, ogg, mp3 (magic-byte sniff; Content-Type is advisory) |
| **Max file size** | `STT_MAX_AUDIO_SIZE_MB` (default **8.0** MB) |
| **Max duration** | `STT_MAX_DURATION_SECONDS` (default **60** s; WAV duration checked) |
| **Service entry** | `transcribe_audio_entry()` in `app/services/voice/stt_service.py` |
| **Engine** | `faster-whisper` when installed |
| **Temporary files** | Written via `write_temp_audio()`; deleted in `finally` inside `transcribe_audio()` |
| **Timeout** | Semaphore acquire timeout = `STT_TIMEOUT_SECONDS` (default **90** s) |
| **Success field** | `success: bool` in service dict / `TranscribeResponse.success` |
| **Transcription field** | `text` (also `original_transcript`, `normalized_transcript`) |
| **low_confidence** | `low_confidence: bool` when `language_probability < STT_MIN_CONFIDENCE` (default 0.35) |
| **Empty transcript** | `success: false`, `error: empty_transcript`, `message_key: empty_audio` |
| **Errors** | Controlled dict (`success: false`, `error`, `message_key`) — service does not raise to callers |
| **Rate limit** | Per-citizen on HTTP endpoint only (IVR bypasses HTTP; calls service directly) |

IVR-A2 calls **`transcribe_audio_entry()`** directly (same pipeline as the HTTP endpoint) with bytes + `language_hint` derived from the A1 session — **no JWT, no HTTP loopback**.

---

## 2. Exotel audio transport analysis

| Option | Assessment |
|--------|--------------|
| **A. Recorded-audio callback (`RecordingUrl`)** | **Selected.** Exotel Voicemail applet records caller speech (MP3). The next applet GET receives `RecordingUrl` (documented for Voicemail → Connect/Gather). Synchronous, smallest slice, no streaming infra. |
| **B. VoiceBot / real-time streaming** | Not selected — requires WebSocket/streaming adapter; out of scope for A2. |
| **C. StatusCallback POST** | Async terminal webhook with `RecordingUrl`; useful for logging but not required for synchronous Flow step. A2 uses GET `RecordingUrl` on Flow transition. |

### Exotel `RecordingUrl` contract (documented)

- Passed as **GET query parameter** when the previous applet was **Voicemail** (also on StatusCallback POST when recording enabled).
- Value is an **HTTPS URL** to Exotel-hosted storage (commonly **AWS S3**, e.g. `s3-ap-southeast-1.amazonaws.com`).
- Format: typically **MP3** (mono telephony).
- URL may be **temporary / time-limited**; fetch promptly after callback.
- **Delay possible** before recording is available (Exotel docs).
- Fetch timeout configured: `EXOTEL_RECORDING_FETCH_TIMEOUT_SECONDS` (default 30 s).

---

## 3. Selected architecture

```
Inbound call
  → A1 GET /api/ivr/language (DTMF → kn/hi/en session)
  → Exotel Say ("Please speak after the beep")
  → Exotel Voicemail applet
  → GET /api/ivr/transcribe?CallSid=…&RecordingUrl=…
       → exotel_recording.py (SSRF-safe HTTPS fetch → temp file → bytes)
       → stt_adapter.py (CallSid → KN/HI/EN hint)
       → transcribe_audio_entry()  [existing STT]
       → session.transcription
       → JSON gather_prompt (no transcript in HTTP body)
  → Exotel Flow → Hangup or retry Voicemail
```

**Dev/test path:** `POST /api/ivr/transcribe?CallSid=…` with multipart `audio` (same field name as voice endpoint) — no Exotel URL required.

---

## 4. Language mapping

| A1 session | STT `language_hint` |
|------------|---------------------|
| `kn` | `KN` |
| `hi` | `HI` |
| `en` | `EN` |

Query params `language_hint`, `lang`, `language` are **ignored** on IVR endpoints.

Missing language → **400** (no silent default).

---

## 5. Security & privacy

- **SSRF:** `validate_exotel_recording_url()` — HTTPS only; allowlisted host suffixes (`.exotel.com`, `.exotel.in`, `.amazonaws.com`); blocks localhost, private IPs, `file://`, `data://`, arbitrary domains.
- **Logging:** `"ivr_stt_ok call_sid=… request_id=…"` — **no transcript, no audio bytes**.
- **Response:** Generic prompts only; transcript stored in session, not returned to Exotel.
- **Cleanup:** Download temp file deleted in `finally`; STT temp deleted by existing service.
- **No permanent recording** stored by GramSakhi.

---

## 6. Error & retry behavior

| Condition | HTTP | Caller prompt |
|-----------|------|---------------|
| Missing `CallSid` | 400 | — |
| Unknown `CallSid` / no language | 400 | — |
| Missing `RecordingUrl` / audio | 200 | Retry prompt |
| Invalid / oversized audio | 200 | Retry or goodbye |
| STT failure / empty / low confidence | 200 | Retry or goodbye |
| Max STT retries (`MAX_STT_RETRY_ATTEMPTS=2`) | 200 | Goodbye |

**No automatic retry of STT POST** — single service invocation per request; telephony retry is Flow-level re-entry.

---

## 7. Exotel Flow changes (after A1)

1. After language confirmation → **Say**: "Please tell us your question after the beep."
2. **Voicemail** applet (records caller speech).
3. **Passthru / Connect / Gather** with Application URL:  
   `https://<api-host>/api/ivr/transcribe?CallSid={CallSid}&RecordingUrl={RecordingUrl}`
4. On `success: true` in JSON → Hangup (or next phase in A3+).
5. On retry prompt → loop to Say + Voicemail (bounded by backend goodbye text).

---

## 8. Known limitations

- In-memory session (same as A1).
- Voicemail recording delay may require Flow retry/pause.
- MP3 telephony quality; no streaming.
- IVR STT does not use citizen JWT rate limits (service-level concurrency only).
- **LIVE TELEPHONY NOT TESTED** in CI.

---

## 9. Verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest tests.test_ivr_a2 -v
.\.venv\Scripts\python.exe scripts\ivr_a2_verify.py
```

OpenAPI: `/docs` → tag **ivr** → `/api/ivr/transcribe`.
