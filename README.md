# GramSakhi

**GramSakhi: RAG-Based Vernacular GenAI LLM for Last-Mile Governance**

Citizen-facing government scheme assistant (web, Android, IVR) with RAG over verified government sources.

Converted from Sahyog 1.0. Historical notes: `migration_audit.md`, `docs/sahyog_to_gramsakhi_migration.md`. Compatibility names: `docs/LEGACY_COMPATIBILITY.md`.

## Phase 2 review

- Mentor pack: [`docs/PHASE_2_REVIEW.md`](docs/PHASE_2_REVIEW.md)
- Demo checklist: [`docs/DEMO_CHECKLIST.md`](docs/DEMO_CHECKLIST.md)
- System check: `cd backend && .\.venv\Scripts\python.exe scripts\gramsakhi_system_check.py`  
  or `GET http://127.0.0.1:8000/health/system`

## Project structure

- `backend/` — FastAPI API (citizen auth, admin, RAG, live government, voice, IVR)
- `frontend/gramsakhi/` — **Unified** GramSakhi web app (**5173**)
  - `/` landing
  - `/citizen/login` → `/chat`
  - `/admin/login` → `/admin`, `/admin/knowledge`, `/admin/registry`
- `mobile/` — Android (Expo) citizen app
- `docs/` — architecture, demo, and historical migration notes

## Local development

### Terminal 1 — Ollama (if not already a service)

```powershell
ollama serve
# ollama pull nomic-embed-text && ollama pull llama3.2:3b
```

### Terminal 2 — Backend (port 8000)

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API docs: http://127.0.0.1:8000/docs

**PostgreSQL dev + Android OTP testing:** see [`backend/docs/OTP_DEV_RETRIEVAL.md`](backend/docs/OTP_DEV_RETRIEVAL.md) for the development-only OTP retrieval endpoint (manual use; never enable in production).

### Terminal 3 — Unified frontend (port 5173)

```powershell
cd frontend/gramsakhi
npm install
npm run dev
```

App: http://127.0.0.1:5173

In Cursor, **“hey shaki”** starts API + unified frontend.

| Surface | URL |
|---------|-----|
| Landing | http://127.0.0.1:5173/ |
| Citizen login | http://127.0.0.1:5173/citizen/login |
| Chat | http://127.0.0.1:5173/chat |
| Admin login | http://127.0.0.1:5173/admin/login |
| Admin | http://127.0.0.1:5173/admin |

Prefer **127.0.0.1** on Windows (avoids localhost↔IPv6 mismatches).

### Optional: Playwright (JS-heavy government sites)

```powershell
cd backend
pip install playwright
playwright install chromium
```

## Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

```powershell
cd frontend/gramsakhi
npm run build
```

## Migration notes

See `migration_audit.md` and `docs/sahyog_to_gramsakhi_migration.md` (historical).
Physical table/API aliases: `docs/LEGACY_COMPATIBILITY.md`.
