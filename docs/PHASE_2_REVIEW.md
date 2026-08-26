# GramSakhi — Phase 2 Mentor Review

## 1. Project objective

GramSakhi is a vernacular, evidence-grounded government-scheme assistant for last-mile citizens. It answers in English, Kannada, and Hindi (text + voice) using verified government documents — never inventing eligibility, amounts, or dates.

## 2. Architecture

```
Citizen → Auth/OTP → Conversation → Language detection → Query rewrite
  → Multilingual retrieval → FAISS + BM25 + CrossEncoder
  → Evidence Sufficiency Validator
       PASS → Ollama → grounded answer → optional TTS
       FAIL → Live government retrieval (trusted registry only)
              → adaptive acquisition → existing ingestion → Supabase
              → FAISS/BM25 refresh → second retrieval → Validator → Ollama
```

Voice is an adapter (Whisper STT → same chat pipeline → Edge TTS). Chat history is conversation-scoped in Supabase; government knowledge is shared.

## 3. Major features

- Unified chat (auto language detection — no EN/KN/HI mode switcher)
- Hybrid RAG + Evidence Validator hard gate
- Live government fallback (myScheme + curated registry)
- Multimodal public acquisition (HTML/JS/PDF/OCR/API/media) — read-only, no auth bypass
- Chat history (new / resume / search / rename / soft-delete)
- Citizen voice STT/TTS
- Super-admin knowledge base + trusted registry UI

## 4. Technology stack

| Layer | Tech |
|-------|------|
| API | FastAPI, SQLAlchemy |
| DB / storage | Supabase PostgreSQL + Storage |
| Retrieval | FAISS + BM25 + CrossEncoder |
| LLM / embeddings | Ollama (`llama3.2:3b`, `nomic-embed-text` / 768) |
| STT / TTS | faster-whisper, edge-tts |
| Browser acquisition | Playwright Chromium |
| Frontend | React + Vite unified app on 5173 (`frontend/gramsakhi`) |

## 5. Live government retrieval

Triggered only when indexed evidence **FAIL**s the validator. Sources must be in the trusted registry. Linked domains from myScheme do **not** inherit trust. CAPTCHA/login/OTP → stop + official-link guidance.

## 6. Multilingual support

Automatic detection for EN / KN / HI. Explicit instructions (“answer in Hindi”) override. Internal English discovery queries must not force English answers. See `backend/docs/UNIFIED_LANGUAGE.md`.

## 7. Voice support

See `backend/docs/VOICE.md`. Voices: `en-IN-NeerjaNeural`, `kn-IN-SapnaNeural`, `hi-IN-SwaraNeural`. TTS/STT failure must not break text chat.

## 8. Supabase architecture

- Auth/session tables + `conversations` / `messages`
- `rag_documents` / `document_chunks` (+ embeddings)
- Storage bucket for document bytes
- Soft-delete conversations never deletes shared government knowledge

## 9. Security

- JWT auth; conversation ownership checks
- SSRF blocks (localhost, private IPs, metadata)
- Trusted registry + redirect validation
- No CAPTCHA/login bypass
- File size / MIME limits on uploads and voice

## 10. Evidence validation

Every factual answer requires Evidence Validator **PASS**. Live-acquired content is ingested and re-validated — never “live PDF → Ollama”.

## 11. Chat history

Sidebar: new chat, search, rename, soft-delete, resume. Opening history does **not** re-run RAG. Conversations are isolated (no cross-conversation evidence leakage).

## 12. Known limitations

- Live government sites may timeout, show CAPTCHA, or be SPA-thin → citizen gets guidance + official links, not invented facts
- First Whisper model download / CrossEncoder warmup can be slow
- IVR / telephone is roadmap only (not demoable)
- Live overall timeout can be up to ~240s for hard acquisitions
- Local `*.db` files may exist; demo uses Supabase when `DATABASE_URL` is Postgres

## 13. Demo instructions

See `docs/DEMO_CHECKLIST.md` and the mentor demo script below.

### Mentor demo script

1. **Basic:** “What is PM-KISAN?” → fast indexed answer  
2. **Follow-up:** “Who is eligible?” → same conversation context  
3. **Kannada:** “ಶಕ್ತಿ ಯೋಜನೆಗೆ ಯಾರು ಅರ್ಹರು?” → Kannada answer  
4. **Language switch:** “Tell me the same thing in Hindi.” → Hindi  
5. **Live (optional):** question with thin indexed evidence → live → ingest → answer  
6. **Reuse:** same question again → indexed, no unnecessary re-download  
7. **Voice:** speak a Kannada scheme question → transcript → answer → TTS  
8. **History:** New Chat → other scheme → return to PM-KISAN conversation  

## 14. Troubleshooting

| Symptom | Check |
|---------|--------|
| Wrong / empty RAG | `GET /health/system`, Ollama models, `indexes/` dim=768 |
| Still on SQLite | `backend/.env` `DATABASE_URL`; kill stale uvicorn; `/health/db` |
| CORS / blank API | Use `http://127.0.0.1` consistently (not mix with `localhost`) |
| OTP | Printed in API terminal as `VERIFICATION OTP: …` |
| Playwright missing | `playwright install chromium` inside `backend/.venv` |
| Live slow | Wait; or ask a known indexed scheme for the demo |

System check:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\gramsakhi_system_check.py
# or: GET http://127.0.0.1:8000/health/system
```

## 15. Startup commands (Windows)

**Terminal A — Ollama** (if not already a service):

```powershell
ollama serve
# ensure: ollama pull nomic-embed-text && ollama pull llama3.2:3b
```

**Terminal B — API** (from repo `backend/`):

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal C — Unified frontend** (`frontend/gramsakhi/`):

```powershell
npm run dev
```

Or say **“hey shaki”** in Cursor to start API + unified frontend.

URLs:

- API docs: http://127.0.0.1:8000/docs  
- App: http://127.0.0.1:5173  
- Citizen login: http://127.0.0.1:5173/citizen/login  
- Chat: http://127.0.0.1:5173/chat  
- Admin: http://127.0.0.1:5173/admin  

## 16. Test results

Run from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Latest full run (Phase 2 readiness pass):

| Metric | Value |
|--------|-------|
| Total | 264 |
| Passed | 264 |
| Failed | 0 |
| Errors | 0 |
| Skipped | 0 |

Demo seed (if Shakti / PMFBY missing from KB):

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\seed_demo_schemes.py
# then admin POST /indexes/rebuild or restart API
```
