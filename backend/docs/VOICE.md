# GramSakhi Phase 7 — Voice (STT / TTS)

Voice is an **input/output adapter** around the existing text GramSakhi pipeline.
It does **not** redesign RAG, Evidence Validator, live government retrieval, or language quality.

## Models

| Role | Engine | Default | Notes |
|------|--------|---------|--------|
| STT | `faster-whisper` | `base` (~150MB first download) | Local; CPU `int8` by default; `cuda` optional via `STT_DEVICE` |
| TTS | `edge-tts` | Neural voices | Network voices: EN `en-IN-NeerjaNeural`, KN `kn-IN-SapnaNeural`, HI `hi-IN-SwaraNeural` |

If either package is missing, `/health/stt` or `/health/tts` reports unavailable and **text chat continues**.

## Flow

1. Browser records audio (MediaRecorder / webm)
2. `POST /api/chat/voice/transcribe` → transcript + `detected_language`
3. Citizen previews/edits text
4. `POST /api/chat` (existing) with optional `stt_language`, `input_mode=voice`
5. Grounded answer (RAG → Evidence → optional live → Ollama → language quality)
6. Optional `POST /api/chat/voice/synthesize` with `response_language`
7. Browser plays MP3; **text answer remains visible**

## Audio policy

- Temporary files only; deleted after STT
- Never stored in Supabase `rag-documents`
- Size/duration limits: `STT_MAX_AUDIO_SIZE_MB`, `STT_MAX_DURATION_SECONDS`
- Bounded concurrency: `STT_MAX_CONCURRENT`, `TTS_MAX_CONCURRENT`

## Windows setup

```powershell
cd backend
.\.venv\Scripts\pip.exe install faster-whisper edge-tts
# Install ffmpeg and ensure it is on PATH (recommended for webm decode)
```

## Health

- `GET /health/stt`
- `GET /health/tts`
- Also under `/api/chat/health/stt` and `/api/chat/health/tts`

## Latency (measured on Windows CPU, this machine)

- TTS edge-tts EN/KN/HI short sentences: ~1.1–1.4s (MP3 `audio/mpeg`)
- STT `base` first load + empty tone clip: ~18s (includes model download/warmup); subsequent short clips typically ~1–5s
- Total voice E2E dominated by RAG/live/LLM, not STT/TTS alone

## Audio response format (TTS)

- Codec: MP3 (via edge-tts)
- MIME: `audio/mpeg`
- Sample rate / bitrate: engine defaults (browser-compatible)

## Models selected

- **STT:** `faster-whisper` 1.2.1, Whisper `base` (~150MB), CPU `int8`, optional CUDA
- **TTS:** `edge-tts` 7.2.8 — `en-IN-NeerjaNeural`, `kn-IN-SapnaNeural`, `hi-IN-SwaraNeural`

Local Whisper preferred for citizen privacy (audio not sent to a third-party STT API). Edge TTS uses Microsoft neural voices over the network for acceptable KN/HI quality without a large local TTS model.
