# IVR-A4 — TTS + Phone Playback

IVR-A4 converts A3 grounded response text into temporary MP3 audio for Exotel playback using the **existing** GramSakhi TTS service.

**LIVE TELEPHONY NOT TESTED** unless a real Exotel call fetched the audio URL.

---

## 1. Existing TTS contract (audited)

| Item | Value |
|------|-------|
| **HTTP endpoint** | `POST /api/chat/voice/synthesize` |
| **Method** | POST |
| **Auth** | JWT Bearer (citizen) |
| **Request body** | `SynthesizeRequest`: `text` (1–5000), `response_language`, optional `request_id` |
| **Service entry** | `synthesize_speech_entry(text, language=..., request_id=...)` |
| **Engine** | `edge-tts` when installed |
| **Output** | **Binary MP3** in service dict (`audio` bytes) |
| **MIME** | `audio/mpeg` |
| **Voices** | EN `en-IN-NeerjaNeural`, KN `kn-IN-SapnaNeural`, HI `hi-IN-SwaraNeural` |
| **Success** | `success: true`, `audio` bytes, `mime_type`, `language`, `voice` |
| **Errors** | Controlled dict (`tts_disabled`, `tts_busy`, `tts_empty`, `tts_failed`) |
| **Timeout** | `TTS_TIMEOUT_SECONDS` (default 60s) |
| **Temp files** | None persisted by TTS service (in-memory bytes + optional cache) |

IVR-A4 calls **`synthesize_speech_entry()`** directly — no JWT, no HTTP loopback.

---

## 2. Exotel playback analysis

**Selected mechanism:** Exotel Connect dynamic URL → `start_call_playback` with `type: audio_url`.

```json
{
  "start_call_playback": {
    "playback_to": "both",
    "type": "audio_url",
    "value": "https://<IVR_PUBLIC_BASE_URL>/api/ivr/audio/<opaque-token>"
  }
}
```

Exotel requirements (documented):
- HTTPS URL returning HTTP 200
- MP3 or WAV, mono telephony (8 kHz documented; MP3 from edge-tts accepted)
- Dynamic filenames recommended (opaque token satisfies this)
- HEAD supported on audio URL (implemented)

**Not selected:** Exotel Say (would use Exotel TTS, not GramSakhi), VoiceBot streaming.

---

## 3. Audio format

| Stage | Format |
|-------|--------|
| GramSakhi TTS output | MP3 (`audio/mpeg`) |
| Exotel requirement | MP3 or WAV mono |
| Conversion | **None required** |

---

## 4. Architecture

```
A3 last_response_text on CallSid session
  → POST /api/ivr/tts { CallSid }
  → tts_adapter → synthesize_speech_entry()
  → audio_token_store (opaque token + temp file)
  → audio_url from IVR_PUBLIC_BASE_URL
  → Exotel fetches GET /api/ivr/audio/{token}
  → single-use serve + delete
```

---

## 5. Configuration

```env
IVR_PUBLIC_BASE_URL=https://api.example.in
IVR_AUDIO_TOKEN_TTL_SECONDS=300   # implicit default in settings
```

- **Never** built from `Host` / `X-Forwarded-Host`
- Production (`APP_ENV=production`) requires HTTPS base URL
- Private/localhost bases rejected

---

## 6. Security

- Opaque `secrets.token_urlsafe(32)` tokens
- Single-use consume on GET
- TTL expiry → 404
- No path traversal (`..`, `/`, `\` rejected)
- No JWT in URLs
- No CallSid in URL
- No audio content in logs

---

## 7. Exotel Flow (after A3)

1. POST `/api/ivr/chat` → grounded text stored on session
2. POST `/api/ivr/tts` → receive `start_call_playback` JSON
3. Exotel Connect applet uses dynamic URL response OR merge `start_call_playback` into Connect JSON
4. Exotel fetches `audio_url` → caller hears response
5. Hangup or next phase (A5+)

---

## 8. Verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest tests.test_ivr_a4 -v
.\.venv\Scripts\python.exe scripts\ivr_a4_verify.py
```

OpenAPI: `/docs` → **ivr** → `POST /api/ivr/tts`, `GET /api/ivr/audio/{token}`

---

## 9. Runtime validation

| Level | Status |
|-------|--------|
| STATICALLY VERIFIED | Yes |
| UNIT TESTED | Yes |
| ACTUAL PHONE TESTED | **NOT TESTED** |

---

## 10. Known limitations

- In-memory token store (dev); multi-instance needs shared storage
- `IVR_PUBLIC_BASE_URL` must be reachable by Exotel (not localhost in production)
- Max text 5000 chars (existing TTS limit); no summarization/truncation
- Long answers may exceed practical telephony playback duration
