# Sahyog → GramSakhi Migration Log

## Phase 0 — Repository Audit

**Status:** COMPLETE

- Created `migration_audit.md`
- No application code changes

## Phase 1 — Remove Healthcare Domain

**Status:** COMPLETE

### Implemented

- Detached clinical API routers (`patients`, `timeline`, `summarize`) from FastAPI startup
- Moved healthcare modules to `backend/app/_legacy_healthcare/` (not imported)
- Citizen auth without Patient/Aadhaar clinical registration
- Admin API reduced to login + dashboard + knowledge-base (no hospital CRUD)
- RAG ingest decoupled from hospital scoping; scheme metadata fields added
- Added `Conversation` / `Message` models (foundation for Phase 6)
- Rebranded admin / citizen / landing UIs to GramSakhi
- Hospital portal replaced with retirement notice
- Citizen Ask UI scaffold (RAG answers deferred to later phases)
- Updated backend tests for hospital-free ingest

### Modified

- `backend/app/main.py`
- `backend/app/core/config.py`
- `backend/app/api/endpoints/auth.py`
- `backend/app/api/endpoints/super_admin.py`
- `backend/app/schemas/auth.py`
- `backend/app/schemas/super_admin_schema.py`
- `backend/app/models/family_account.py`
- `backend/app/models/rag.py`
- `backend/app/services/rag.py`
- `backend/tests/test_super_admin.py`
- Admin / citizen / landing / hospital frontends
- `README.md`

### Created

- `backend/app/models/conversation.py`
- `backend/app/_legacy_healthcare/**` (moved healthcare code)
- `frontend/patient_portal/src/pages/AskGramSakhi.jsx`
- `docs/sahyog_to_gramsakhi_migration.md`

### Removed from active path (preserved under `_legacy_healthcare`)

- Patient / timeline / summarize endpoints
- Hospital / doctor / clinical services
- Gemini clinical summarizer provider
- Patient / hospital ORM models (active app)

### Tests

- `python -m unittest backend.tests.test_super_admin` (run from backend with PYTHONPATH)

### Known issues

- Existing SQLite DBs created under Sahyog may lack new columns (`scheme_name`, `indexing_status`, `display_name`, conversations). Prefer a fresh DB or manual ALTER for local demos.
- Citizen Ask UI does not yet call RAG/LLM (Phases 3–5).
- pgvector retrieval remains until Phase 3 FAISS+BM25+CE cutover.
- Document upload still depends on Supabase storage credentials when configured.
- Vite ports for portals may differ; landing links assume common local ports.

### Next phase

**Phase 2 — Government Knowledge Base** (OCR fallback, richer metadata, sample scheme docs, indexing status UX)

---

## Web government ingestion (non-destructive add-on)

**Status:** COMPLETE

### Files created
- `backend/app/services/web_ingestion_service.py`
- `backend/app/config/gov_sources.py`
- `backend/data/scheme_catalog.json`
- `backend/app/background_jobs/web_ingest_scheduler.py`
- `backend/tests/test_web_ingestion.py`

### Files modified
- `backend/app/services/rag.py` — added `ingest_raw_bytes` shared entry (manual upload calls it)
- `backend/app/services/storage.py` — local fallback when Supabase unset
- `backend/app/api/endpoints/super_admin.py` — `GET /ingest/sources`, `POST /ingest/web`
- `backend/app/schemas/super_admin_schema.py` — WebIngestRequest/Response
- `backend/app/main.py` — optional scheduler startup
- `backend/requirements.txt` — httpx, beautifulsoup4

### What was NOT modified
- Retrieval logic (`retrieve_similar_chunks` unchanged in behavior)
- Embedding provider (still Ollama via existing helpers)
- LLM / conversation rewrite paths

### Admin API
```text
GET  /api/v1/super-admin/ingest/sources
POST /api/v1/super-admin/ingest/web
Body: { "source": "karnataka"|"central"|"pm-kisan", "max_docs": 5, "query": optional, "urls": optional }
```

### Tests
- `unittest tests.test_web_ingestion` + `tests.test_super_admin` → 13/13 passed

---

## Web ingestion hardening

**Status:** COMPLETE

### Improved
- SHA-256 `document_hash` dedupe (idempotent re-runs)
- PDF-first crawl when HTML pages expose PDF links
- HTML quality gate (`MIN_HTML_CHARS = 500`)
- `normalize_metadata()` for scheme_name / state / category / source
- Source versioning via `document_hash` + `last_ingested_at`
- Scheduler threshold skip via `data/web_ingest_last_run.json`
- Structured ingest logs (fetched / skipped duplicate / low content / success)

### Tests
- Hardening suite + manual ingest regression → 15/15 passed
