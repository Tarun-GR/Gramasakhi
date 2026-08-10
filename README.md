# GramSakhi

**GramSakhi: RAG-Based Vernacular GenAI LLM + IVR System for Last-Mile Governance**

Converted from Sahyog 1.0 (Phase 1 in progress). Healthcare clinical workflows have been removed from the active application path.

## Project structure

- `backend/` — FastAPI API (citizen auth, admin auth, knowledge-base ingest)
- `frontend/landing_portal/` — GramSakhi landing
- `frontend/patient_portal/` — Citizen Ask GramSakhi (React/Vite)
- `frontend/super_admin_portal/` — Admin knowledge-base management
- `frontend/hospital_portal/` — Retired clinical UI (redirect notice only)
- `backend/app/_legacy_healthcare/` — Preserved Sahyog healthcare modules (not imported)

## Backend

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

API docs: http://127.0.0.1:8000/docs

## Frontends

| Portal | Command | Default URL |
|--------|---------|-------------|
| Landing | `cd frontend/landing_portal && npm install && npm run dev` | http://localhost:5173 |
| Admin | `cd frontend/super_admin_portal && npm install && npm run dev` | http://localhost:5174 (or Vite-assigned) |
| Citizen | `cd frontend/patient_portal && npm install && npm run dev` | http://localhost:5176 (configure port if needed) |

## Migration status

See `migration_audit.md` and `docs/sahyog_to_gramsakhi_migration.md`.

**Phase 0** — Audit complete  
**Phase 1** — Healthcare domain removed from active path  
**Phases 2–8** — Government KB polish, FAISS+BM25+CE, evidence gate, Ollama generation, conversation rewrite, STT/TTS, IVR
