# GramSakhi — Architecture Map (Top → Bottom)

Structural inventory only. No design commentary.

---

## LAYER 0 — REPOSITORY

```
GramSakhi/
├── backend/                    # FastAPI API (:8000)
├── frontend/
│   └── gramsakhi/              # Unified SPA (:5173)
├── mobile/                     # Android (Expo)
├── docs/
│   ├── ARCHITECTURE.md         # This file
│   ├── LEGACY_COMPATIBILITY.md
│   ├── DEMO_CHECKLIST.md
│   └── PHASE_2_REVIEW.md
└── README.md
```

---

## LAYER 1 — FRONTEND (`frontend/gramsakhi/`)

### 1.1 Root files

| File | Contains |
|------|----------|
| `package.json` | React 19, Vite 8, React Router 7, Tailwind, Axios |
| `index.html` | SPA shell |
| `vite.config.js` | Dev server :5173 |
| `.env.example` | `VITE_API_BASE_URL`, `VITE_USE_MOCK` |

### 1.2 `src/` — entry

| File | Contains |
|------|----------|
| `main.jsx` | React root mount |
| `App.jsx` | Routes, `CitizenProtected`, `CitizenGuest`, `GlobalToast` |
| `App.css`, `index.css` | Global styles |

### 1.3 `src/landing/`

| File | Contains |
|------|----------|
| `Landing.jsx` | Public landing page |
| `components/ui/Btn.jsx` | Button component |

### 1.4 `src/pages/` — citizen

| File | Contains |
|------|----------|
| `Login.jsx` | Password / OTP login |
| `Register.jsx` | New citizen account |
| `ForgotPassword.jsx` | Password reset |
| `OTPVerification.jsx` | OTP verify step |
| `GramSakhiChat.jsx` | Chat shell (`AppShell` / gramsakhi-ui) |

### 1.5 `src/components/`

| Path | Contains |
|------|----------|
| `auth/ForgotPassword.jsx` | Forgot password form |

### 1.6 `src/context/`

| File | Contains |
|------|----------|
| `AuthContext.jsx` | `citizenAccountId`, login/logout, OTP, toast |

### 1.7 `src/services/`

| File | Contains |
|------|----------|
| `api.js` | Axios → `http://127.0.0.1:8000/api`, Bearer `accessToken` |

### 1.8 `src/admin/` — admin portal

| File | Contains |
|------|----------|
| `AdminShell.jsx` | Admin layout, `AdminProtected`, nested routes |
| `App.css` | Admin dark theme styles |
| `components/Sidebar.jsx` | Nav: Dashboard, Knowledge, Registry |
| `components/Header.jsx` | Page title bar |
| `components/ConfirmDialog.jsx` | Delete confirm modal |
| `pages/Login.jsx` | Admin login |
| `pages/Dashboard.jsx` | Stats summary |
| `pages/KnowledgeBase.jsx` | Document list / upload |
| `pages/DocumentDetail.jsx` | Chunks per document |
| `pages/GovRegistry.jsx` | Trusted source registry UI |
| `services/api.js` | Axios → `/api/v1/super-admin`, Bearer `superAdminToken` |

### 1.9 Frontend routes

```
/                           → Landing.jsx
/citizen/login              → Login.jsx
/citizen/register           → Register.jsx
/citizen/forgot-password    → ForgotPassword.jsx
/citizen/verify-otp         → OTPVerification.jsx
/chat                       → GramSakhiChat.jsx
/chat/:conversationId       → GramSakhiChat.jsx
/admin/login                → admin/pages/Login.jsx
/admin                      → admin/pages/Dashboard.jsx
/admin/knowledge            → admin/pages/KnowledgeBase.jsx
/admin/knowledge/:documentId → admin/pages/DocumentDetail.jsx
/admin/registry             → admin/pages/GovRegistry.jsx
```

### 1.10 Frontend → API calls

| UI | HTTP |
|----|------|
| Citizen auth | `POST /api/auth/login`, `/otp/send`, `/otp/verify`, `/register`, `/forgot-password/*` |
| Chat | `POST /api/chat`, `GET/PATCH/DELETE /api/chat/conversations/*` |
| Voice | `POST /api/chat/voice/transcribe`, `/voice/synthesize` |
| Admin | `POST /api/v1/super-admin/auth/login`, `/dashboard/summary`, `/knowledge-base/*`, `/gov-registry/*`, `/indexes/rebuild`, `/ingest/web`, `/retrieve/hybrid`, `/query` |

---

## LAYER 2 — BACKEND ENTRY (`backend/`)

### 2.1 Root files

| File | Contains |
|------|----------|
| `requirements.txt` | Python dependencies |
| `.env` | Runtime secrets (not committed) |
| `.env.example` | Env template |
| `gramsakhi.db` | Local SQLite fallback DB (default). Older `sahyog.db` files may still exist. |
| `scripts/gramsakhi_system_check.py` | CLI system check |
| `scripts/seed_demo_schemes.py` | Demo KB seed |
| `scripts/myscheme_content_smoke.py` | MyScheme smoke test |

### 2.2 On-disk runtime data

```
backend/
├── data/
│   ├── trusted_gov_registry.json      # Allowed gov domains/sources
│   ├── scheme_catalog.json            # Scheme name/URL catalog
│   ├── myscheme_discovery_cache.json  # MyScheme discovery cache
│   ├── demo_seeds/*.txt               # Demo scheme text
│   └── seed_schemes/*.txt             # Seed overview text
├── indexes/                           # Hybrid RAG indexes
│   ├── faiss.index
│   ├── faiss_ids.json
│   ├── bm25_model.pkl
│   ├── bm25_meta.json
│   └── chunk_lookup.json
└── static/uploads/                    # Local file fallback (Supabase off)
```

---

## LAYER 3 — BACKEND APP (`backend/app/`)

### 3.1 `main.py`

| Item | |
|------|--|
| `FastAPI` app | CORS, static mount `/static` |
| Startup | `create_all`, `ensure_sqlite_columns`, Ollama ping, web-ingest scheduler, CrossEncoder warmup |
| Routers | `/api/auth`, `/api/chat`, `/api/chat` (voice), `/api/v1/super-admin` |
| Health | `/health`, `/health/db`, `/health/ollama`, `/health/supabase`, `/health/system`, `/health/stt`, `/health/tts` |

---

### 3.2 `core/`

| File | Classes / functions |
|------|---------------------|
| `config.py` | `Settings` (all env flags: DB, Supabase, Ollama, hybrid RAG, evidence gate, live gov, providers, voice, language) |
| `security.py` | JWT encode/decode, password hash/verify, OTP hash |

---

### 3.3 `database/`

| File | Contains |
|------|----------|
| `session.py` | SQLAlchemy `engine`, `SessionLocal`, `Base`, `get_db` |
| `migrations/supabase_schema.sql` | Postgres DDL (see Layer 5) |
| `migrations/run_migrations.py` | `ensure_sqlite_columns()` |
| `migrations/migrate_sqlite_to_supabase.py` | One-off migration script |

---

### 3.4 `models/` → maps to DB tables

| File | SQLAlchemy model | Table |
|------|------------------|-------|
| `citizen_account.py` | `CitizenAccount` | `family_accounts` (compat name) |
| | `CitizenSession` | `family_sessions` (compat name) |
| | `OTPVerification` | `otp_verifications` |
| `user.py` | `User` | `users` |
| `rag.py` | `RagDocument` | `rag_documents` |
| | `DocumentChunk` | `document_chunks` |
| | `PGVector` | Custom vector type |
| `conversation.py` | `Conversation` | `conversations` |
| | `Message` | `messages` |
| `audit.py` | `AuditLog` | `audit_logs` |
| | `ActivityLog` | `activity_logs` |

---

### 3.5 `schemas/` — Pydantic request/response

| File | Contains |
|------|----------|
| `auth.py` | Login, register, OTP, token schemas |
| `chat.py` | `ChatRequest`, `ChatResponse`, conversation schemas |
| `voice.py` | `TranscribeResponse`, TTS schemas |
| `super_admin_schema.py` | KB upload, dashboard, gov registry, ingest schemas |

---

### 3.6 `api/endpoints/` — HTTP handlers

#### `auth.py` → prefix `/api/auth`

| Method | Path |
|--------|------|
| POST | `/login` |
| POST | `/otp/send` |
| POST | `/otp/verify` |
| POST | `/register` |
| POST | `/forgot-password/request` |
| POST | `/forgot-password/reset` |

#### `chat.py` → prefix `/api/chat`

| Method | Path | Handler |
|--------|------|---------|
| GET | `/conversations` | List conversations |
| GET | `/conversations/search` | Search conversations |
| POST | `/conversations` | Create conversation |
| GET | `/conversations/{id}` | Conversation history |
| PATCH | `/conversations/{id}` | Rename |
| DELETE | `/conversations/{id}` | Soft delete |
| POST | `/` | `handle_citizen_chat` |
| GET | `/{conversation_id}` | History (legacy path) |

#### `voice.py` → prefix `/api/chat`

| Method | Path |
|--------|------|
| GET | `/health/stt` |
| GET | `/health/tts` |
| POST | `/voice/transcribe` |
| POST | `/voice/synthesize` |

#### `super_admin.py` → prefix `/api/v1/super-admin`

| Method | Path |
|--------|------|
| POST | `/auth/login` |
| GET | `/dashboard/summary` |
| GET | `/knowledge-base` |
| POST | `/knowledge-base` (upload) |
| GET | `/knowledge-base/{document_id}` |
| GET | `/knowledge-base/{document_id}/chunks` |
| DELETE | `/knowledge-base/{document_id}` |
| GET | `/knowledge-base/{document_id}/download` |
| GET | `/ingest/sources` |
| GET | `/gov-registry` |
| POST | `/gov-registry/refresh` |
| GET | `/gov-registry/health` |
| PATCH | `/gov-registry/{source_id}` |
| POST | `/ingest/web` |
| POST | `/indexes/rebuild` |
| POST | `/retrieve/hybrid` |
| POST | `/query` |

---

### 3.7 `config/`

| File | Contains |
|------|----------|
| `gov_sources.py` | `GOV_SOURCES`, `CENTRAL_HOSTS`, `is_allowed_url()`, `source_category()`, `load_catalog()` |
| `__init__.py` | Package init |

---

### 3.8 `background_jobs/`

| File | Contains |
|------|----------|
| `web_ingest_scheduler.py` | Periodic web ingest thread (`WEB_INGEST_SCHEDULER_ENABLED`) |

---

### 3.9 `services/` — business logic

#### Chat orchestration

| File | Key symbols |
|------|-------------|
| `conversation_service.py` | `handle_citizen_chat()`, message persistence |
| `query_rewriter.py` | `rewrite_query()`, `extract_scheme_mentions()` |
| `language_service.py` | `resolve_response_language()`, script detection |
| `language_quality.py` | Post-LLM KN/HI quality gate |
| `kannada_glossary.py` | Kannada term normalization |
| `citizen_failure_ux.py` | Failure messages, guidance URLs |

#### RAG + indexing

| File | Key symbols |
|------|-------------|
| `rag.py` | `ingest_document()`, `ingest_raw_bytes()`, `hybrid_retrieve()`, `answer_with_evidence_gate()`, `get_embeddings()`, `chunk_text()`, `extract_text_from_bytes()` |
| `faiss_index.py` | FAISS load/search/save |
| `bm25_index.py` | BM25 load/search/save |
| `cross_encoder.py` | CrossEncoder rerank |
| `index_builder.py` | Build indexes from `document_chunks` |
| `evidence_validator.py` | `EvidenceValidator.validate()` |
| `llm_service.py` | `generate_answer()`, `check_ollama_llm()` |
| `prompt_builder.py` | Grounded prompt templates |
| `multilingual_retrieval_service.py` | `expand_for_live_search()`, `multi_query_hybrid_retrieve()`, `build_retrieval_plan()` |

#### Live government acquisition

| File | Key symbols |
|------|-------------|
| `live_gov_retrieval_service.py` | `LiveGovRetrievalService`, `search_government_sources()`, `try_live_gov_fallback()`, `discover_candidate_pages()`, `discover_seed_urls()`, `select_best_candidates()`, `_ingest_ranked_until_sufficient()`, `verify_source()`, `expand_search_query()`, `looks_like_gov_scheme_query()`, `match_catalog_schemes()` |
| `myscheme_service.py` | MyScheme search/discovery/identity: `request_accepts_candidate()`, `filter_evidence_by_scheme()`, `package_myscheme_evidence()`, `required_sections_for_query()`, `requested_scheme_identity()`, `evidence_matches_requested_scheme()` |
| `gov_source_registry.py` | `load_registry()`, `is_domain_in_registry()`, `find_source_for_url()`, IGOD refresh |
| `web_ingestion_service.py` | Admin + scheduled web ingest |
| `storage.py` | Supabase Storage upload/download |
| `audit.py` | Audit log writes |
| `system_check.py` | `run_system_check()`, `format_system_check_text()` |

#### Provider registry (`services/providers/`)

| File | Key symbols |
|------|-------------|
| `base.py` | `GovernmentInformationProvider`, `ProviderContext`, `ProviderRunResult`, `ChainRunResult`, `SchemeCandidate`, `ExtractedEvidence`, `extracted_evidence_is_usable()`, `merge_provider_ingested()`, `log_provider_event()` |
| `registry.py` | `ProviderRegistry.run_chain()` |
| `live_integration.py` | `build_default_registry()`, `search_via_provider_registry()`, `finalize_chain_to_live_response()` |
| `myscheme_provider.py` | `MySchemeProvider` (priority 100) |
| `india_gov_provider.py` | `IndiaGovProvider` (priority 150), `build_india_gov_seeds_for_query()`, `is_india_gov_url()` |
| `data_gov_provider.py` | `DataGovProvider` (priority 175), `build_data_gov_seeds_for_query()`, `dataset_relevant_to_query()`, `discover_data_gov_candidates()` |
| `registry_government_provider.py` | `RegistryGovernmentProvider` (priority 200), `_filter_fallback_seeds()` |
| `__init__.py` | Public exports |

**Provider chain order:** myscheme(100) → india_gov(150) → data_gov(175) → registry_government(200)

#### Acquisition (`services/acquisition/`)

| File | Key symbols |
|------|-------------|
| `base.py` | `AcquisitionResult`, `SourceHealth`, `AcquisitionMethod` |
| `orchestrator.py` | `AcquisitionOrchestrator.acquire()` — static → browser escalation |
| `static_http.py` | HTTP fetch, `discover_document_links()`, `public_api_bytes_to_text()` |
| `browser_playwright.py` | Playwright render for JS pages |
| `reliability.py` | Retry / health classification |
| `__init__.py` | Package init |

#### Voice (`services/voice/`)

| File | Key symbols |
|------|-------------|
| `stt_service.py` | Whisper STT, `get_stt_health()` |
| `tts_service.py` | edge-tts, `get_tts_health()` |
| `rate_limit.py` | Per-user voice rate limits |
| `audio_utils.py` | Audio format conversion |
| `pronunciation.py` | Pronunciation helpers |
| `messages.py` | Voice UX message strings |
| `__init__.py` | Package init |

---

---

## LAYER 4 — REQUEST FLOW (call chain only)

```
POST /api/chat
  chat.py
    conversation_service.handle_citizen_chat
      language_service.resolve_response_language
      query_rewriter.rewrite_query
      rag.answer_with_evidence_gate
        multilingual_retrieval_service (retrieval plan)
        rag.hybrid_retrieve
          faiss_index.search
          bm25_index.search
          cross_encoder.rerank
        myscheme_service.filter_evidence_by_scheme
        evidence_validator.EvidenceValidator.validate
        [PASS] llm_service.generate_answer
               language_quality (optional)
        [FAIL] live_gov_retrieval_service.try_live_gov_fallback
               providers.live_integration.search_via_provider_registry
                 providers.registry.ProviderRegistry.run_chain
                   myscheme_provider.MySchemeProvider.run
                   india_gov_provider.IndiaGovProvider.run
                   data_gov_provider.DataGovProvider.run
                   registry_government_provider.RegistryGovernmentProvider.run
               live_gov_retrieval_service (discover + ingest + index rebuild)
               rag.answer_with_evidence_gate (live disabled)
        [FAIL] citizen_failure_ux
      conversation_service (persist Message rows)
```

---

## LAYER 5 — DATABASE

### 5.1 Engine

| Config | Engine |
|--------|--------|
| `DATABASE_URL` (Postgres/Supabase) | PostgreSQL + pgvector |
| Fallback | SQLite (`backend/gramsakhi.db`; older `sahyog.db` still readable by the migrator) |

### 5.2 Tables

#### `users` (admin)

| Column | Type |
|--------|------|
| id | UUID PK |
| email | VARCHAR(255) UNIQUE |
| password_hash | VARCHAR(255) |
| first_name | VARCHAR(100) |
| last_name | VARCHAR(100) |
| phone_number | VARCHAR(20) |
| role | VARCHAR(50) |
| is_active | BOOLEAN |
| created_at | TIMESTAMPTZ |
| updated_at | TIMESTAMPTZ |
| deleted_at | TIMESTAMPTZ |

#### `family_accounts` (CitizenAccount — physical name retained)

| Column | Type |
|--------|------|
| id | UUID PK |
| phone_number | VARCHAR(20) UNIQUE |
| password_hash | VARCHAR(255) |
| display_name | VARCHAR(150) |
| is_active | BOOLEAN |
| created_at | TIMESTAMPTZ |
| updated_at | TIMESTAMPTZ |

#### `family_sessions`

| Column | Type |
|--------|------|
| id | UUID PK |
| family_account_id | UUID FK → family_accounts |
| refresh_token | VARCHAR(500) UNIQUE |
| ip_address | VARCHAR(45) |
| user_agent | TEXT |
| expires_at | TIMESTAMPTZ |
| revoked_at | TIMESTAMPTZ |
| created_at | TIMESTAMPTZ |

#### `otp_verifications`

| Column | Type |
|--------|------|
| id | UUID PK |
| phone_number | VARCHAR(20) |
| otp_hash | VARCHAR(255) |
| expires_at | TIMESTAMPTZ |
| verified | BOOLEAN |
| attempt_count | INTEGER |
| created_at | TIMESTAMPTZ |

#### `rag_documents`

| Column | Type |
|--------|------|
| id | UUID PK |
| hospital_id | UUID (legacy, nullable) |
| uploaded_by | UUID FK → users |
| title | VARCHAR(255) |
| file_url | TEXT |
| category | VARCHAR(100) |
| version | VARCHAR(50) |
| scheme_name | VARCHAR(255) |
| ministry | VARCHAR(255) |
| state | VARCHAR(100) |
| source | VARCHAR(255) |
| language | VARCHAR(20) |
| document_type | VARCHAR(100) |
| indexing_status | VARCHAR(50) |
| document_hash | VARCHAR(64) |
| last_ingested_at | TIMESTAMPTZ |
| created_at | TIMESTAMPTZ |
| updated_at | TIMESTAMPTZ |

#### `document_chunks`

| Column | Type |
|--------|------|
| id | UUID PK |
| document_id | UUID FK → rag_documents |
| chunk_index | INTEGER |
| content | TEXT |
| embedding | vector(768) |
| metadata | JSONB |
| created_at | TIMESTAMPTZ |

#### `conversations`

| Column | Type |
|--------|------|
| id | UUID PK |
| citizen_account_id | UUID FK → family_accounts |
| language | VARCHAR(20) |
| title | VARCHAR(255) |
| active_scheme_context | VARCHAR(255) |
| is_active | BOOLEAN |
| deleted_at | TIMESTAMPTZ |
| last_message_at | TIMESTAMPTZ |
| created_at | TIMESTAMPTZ |
| updated_at | TIMESTAMPTZ |

#### `messages`

| Column | Type |
|--------|------|
| id | UUID PK |
| conversation_id | UUID FK → conversations |
| role | VARCHAR(20) — user \| assistant \| system |
| content | TEXT |
| rewritten_query | TEXT |
| language | VARCHAR(20) |
| evidence_status | VARCHAR(20) — SUPPORTED \| UNSUPPORTED |
| input_mode | VARCHAR(20) — text \| voice |
| knowledge_source | VARCHAR(50) |
| sources_json | TEXT |
| official_sources_json | TEXT |
| created_at | TIMESTAMPTZ |

#### `audit_logs`

| Column | Type |
|--------|------|
| id | UUID PK |
| user_id | UUID FK → users |
| action | VARCHAR(50) |
| table_name | VARCHAR(100) |
| record_id | UUID |
| old_values | JSONB |
| new_values | JSONB |
| ip_address | VARCHAR(45) |
| user_agent | TEXT |
| created_at | TIMESTAMPTZ |

#### `activity_logs`

| Column | Type |
|--------|------|
| id | UUID PK |
| user_id | UUID FK → users |
| activity_type | VARCHAR(100) |
| description | TEXT |
| metadata | JSONB |
| ip_address | VARCHAR(45) |
| user_agent | TEXT |
| created_at | TIMESTAMPTZ |

### 5.3 Supabase Storage (outside Postgres)

| Bucket | Content |
|--------|---------|
| `rag-documents` (`SUPABASE_STORAGE_BUCKET`) | Uploaded PDF/TXT source files |

---

## LAYER 6 — INDEXES (on disk, not DB)

| File | Built from | Used by |
|------|------------|---------|
| `indexes/faiss.index` | `document_chunks.embedding` | `faiss_index.py` |
| `indexes/faiss_ids.json` | chunk UUID mapping | `faiss_index.py` |
| `indexes/bm25_model.pkl` | chunk text | `bm25_index.py` |
| `indexes/bm25_meta.json` | BM25 metadata | `bm25_index.py` |
| `indexes/chunk_lookup.json` | chunk id → content/meta | `index_builder.py`, retrieval |

Built by: `index_builder.py`, `POST /api/v1/super-admin/indexes/rebuild`, live gov ingest refresh.

---

## LAYER 7 — JSON DATA FILES (not DB)

### `trusted_gov_registry.json`

```
version, source_directory, directory_urls, last_refreshed_at, last_refresh_status
sources[]:
  id, name, level, state, organization, domain, base_urls[], categories[], source_directory, enabled, priority, health
rejected[]
```

### `scheme_catalog.json`

```
schemes[]:
  name, ministry, state, scope, keywords[], urls[]
```

### `myscheme_discovery_cache.json`

Cached MyScheme discovery results (runtime).

---

## LAYER 8 — EXTERNAL SERVICES

| Service | Port / URL | Used by |
|---------|------------|---------|
| Ollama | `OLLAMA_API_URL` (default :11434) | `rag.py` embeddings, `llm_service.py` generation |
| Supabase Postgres | `DATABASE_URL` | SQLAlchemy ORM |
| Supabase Storage | `SUPABASE_URL` | `storage.py` |
| Playwright Chromium | local | `acquisition/browser_playwright.py` |
| edge-tts | cloud | `voice/tts_service.py` |
| Whisper | local model | `voice/stt_service.py` |
| myScheme.gov.in | HTTPS | `myscheme_service.py`, `MySchemeProvider` |
| india.gov.in | HTTPS | `IndiaGovProvider` |
| data.gov.in | HTTPS | `DataGovProvider` |
| Trusted gov portals | HTTPS | `RegistryGovernmentProvider`, registry JSON |

---

## LAYER 9 — TESTS (`backend/tests/`)

| Area | Files |
|------|-------|
| Providers | `test_gov_providers.py`, `test_myscheme_provider.py`, `test_india_gov_provider.py`, `test_data_gov_provider.py`, `test_registry_government_provider.py` |
| MyScheme | `test_myscheme*.py` (8+ files) |
| RAG / evidence | `test_evidence_validator.py`, `test_multilingual_*.py`, `test_query_rewriter.py` |
| Live gov | `test_live_gov_*.py`, `test_acquisition.py` |
| Voice | `test_voice.py` |
| Chat | `test_chat_*.py` |
| Language | `test_language_*.py`, `test_kannada_quality.py`, `test_translation_quality.py` |
| Ingestion | `test_web_ingestion.py`, `test_gov_source_registry.py` |
| Fixtures | `tests/fixtures/acquisition/*.html`, `tests/fixtures/audio/*.wav` |

---

## LAYER 10 — BACKEND DOCS

| File | Topic |
|------|-------|
| `backend/docs/MULTILINGUAL_RETRIEVAL.md` | Multilingual retrieval bridge |
| `backend/docs/VOICE.md` | STT/TTS |
| `backend/docs/UNIFIED_LANGUAGE.md` | Language resolver |

---

*Structural map — August 2026*
