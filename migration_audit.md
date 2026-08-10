# Phase 0 — Repository Audit: Sahyog → GramSakhi

**Date:** 2026-08-10  
**Workspace:** `C:\Users\tarun\Downloads\Sahyog`  
**Architectural reference (read-only):** `C:\Users\tarun\Downloads\Gramasakhi`  
**Status:** COMPLETE — no application code modified in this phase.  
**Phase 1:** COMPLETE (see `docs/sahyog_to_gramsakhi_migration.md`).

---

## 1. Executive summary

Sahyog 1.0 is a **healthcare multi-portal** system (patient / hospital / super-admin / landing) built on **FastAPI + React/Vite + SQLAlchemy**. It already contains reusable infrastructure for authentication, document ingestion, Ollama embeddings, and a super-admin knowledge-base UI.

It does **not** currently implement the target GramSakhi RAG stack (FAISS + BM25 + CrossEncoder + evidence sufficiency + grounded Ollama generation + conversation rewrite + STT/TTS/IVR). Those capabilities exist in the separate **Gramasakhi** reference project and must be selectively migrated into this codebase.

The `ai/`, `docs/`, `shared/`, `testing/`, `scripts/`, `deployment/`, and most of `infrastructure/` directories are **scaffold-only** (`.gitkeep` placeholders).

---

## 2. Repository map

```text
Sahyog/
├── backend/                 # Working FastAPI app (primary code)
├── frontend/
│   ├── landing_portal/      # React/Vite — healthcare marketing landing
│   ├── patient_portal/      # React/Vite — family/patient auth + dashboard
│   ├── hospital_portal/     # React/Vite — doctor/admin/staff clinical UI
│   ├── super_admin_portal/  # React/Vite — hospitals + RAG knowledge base
│   ├── patient_app/         # Flutter stub (empty pubspec, no real app)
│   └── shared/              # Empty scaffold
├── database/                # PostgreSQL SQL schemas, migrations, seeders
├── ai/                      # EMPTY scaffold (rag, ivr, speech, llm, …)
├── docs/                    # EMPTY scaffold
├── shared/                  # EMPTY scaffold
├── storage/                 # EMPTY folders (medical_documents, rag_documents, voice, …)
├── testing/                 # EMPTY scaffold
├── scripts/                 # EMPTY scaffold
├── deployment/              # EMPTY scaffold
├── infrastructure/          # EMPTY scaffold (docker, nginx, …)
├── docker-compose.yml       # EMPTY file
├── LICENSE                  # EMPTY file
├── .env.example             # Supabase-oriented (root)
├── README.md                # Sahyog healthcare setup docs
└── migration_audit.md       # THIS FILE
```

---

## 3. Backend inventory

### Entry point

| Item | Path | Notes |
|------|------|-------|
| App | `backend/app/main.py` | FastAPI; CORS; mounts routers; Ollama embed health check |
| Config | `backend/app/core/config.py` | Project name, JWT, DB, Supabase, Ollama embeddings |
| Security | `backend/app/core/security.py` | bcrypt, JWT, OTP helpers |
| DB session | `backend/app/database/session.py` | SQLAlchemy engine; SQLite or Postgres via `DATABASE_URL` |

### Routes (mounted today)

| Prefix | Module | Domain |
|--------|--------|--------|
| `/api/auth` | `api/endpoints/auth.py` | Family OTP/password login; employee hospital login |
| `/api/patients` | `api/endpoints/patients.py` | Patient profiles, family members, Aadhaar |
| `/api/patients/timeline` | `api/endpoints/timeline.py` | Clinical timeline / encounters |
| `/api/patients/{id}/summarize` | `api/endpoints/summarize.py` | Gemini clinical summary |
| `/api/v1/super-admin` | `api/endpoints/super_admin.py` | Super-admin auth, hospitals CRUD, KB upload |
| `/` | `main.py` | Welcome message (Sahyog Healthcare) |
| `/health/ollama` | `main.py` | Embedding reachability |

**Missing for GramSakhi:** `/query`, `/chat`, `/conversations`, `/schemes`, `/voice`, `/stt`, `/tts`, `/ivr`, citizen-facing grounded Q&A.

### Models

| File | Entities | Classification |
|------|----------|----------------|
| `models/user.py` | `User` (SUPER_ADMIN, HOSPITAL_ADMIN, DOCTOR, PATIENT) | **MODIFY** roles |
| `models/family_account.py` | FamilyAccount, OTP, sessions | **MODIFY** → citizen session concepts |
| `models/patient.py` | Patient, allergies, meds, conditions, Encounter, HospitalUser, … | **REMOVE** / replace |
| `models/hospital.py` | Hospital, Department, Doctor, HospitalAdmin | **REMOVE** |
| `models/rag.py` | RagDocument, DocumentChunk (pgvector) | **MODIFY** → scheme metadata + FAISS/BM25 alignment |
| `models/audit.py` | AuditLog | **KEEP** (adapt events) |

### Services

| File | Role | Classification |
|------|------|----------------|
| `services/rag.py` | PDF/TXT extract, chunk, Ollama embed, ingest, **pgvector** similarity | **MODIFY** heavily |
| `services/storage.py` | Supabase Storage upload/download/signed URL | **MODIFY** / optional local fallback |
| `services/audit.py` | Audit logging | **KEEP** |
| `services/hospital.py` | Hospital domain | **REMOVE** |
| `services/timeline.py` | Clinical timeline | **REMOVE** |
| `services/summarize.py` | Gemini clinical summarize | **REMOVE** |
| `services/ai_summarizer.py` | Rule/OpenAI clinical summary | **REMOVE** |

### Providers / prompts

| File | Role | Classification |
|------|------|----------------|
| `providers/gemini_provider.py` | Gemini 2.5 Flash | **REMOVE** (do not use for GramSakhi generation) |
| `prompts/summarize_prompt.py` | Clinical summary prompts | **REMOVE** |
| `utils/summarize_formatter.py` | Clinical formatter | **REMOVE** |

### Auth

- JWT via `python-jose` + bcrypt passwords — **KEEP** pattern.
- Family phone/OTP auth — **MODIFY** into citizen/session auth (or session-only for web/IVR).
- Super-admin email/password — **KEEP** as Admin.
- Hospital employee auth (`require_hospital_user`) — **REMOVE**.

### AI / RAG (as implemented in Sahyog)

```text
PDF/TXT → pypdf extract → char chunking (page metadata)
       → Ollama mxbai-embed-large (1024-d)
       → PostgreSQL pgvector (document_chunks.embedding)
       → cosine similarity retrieve_similar_chunks()
```

**Not present in Sahyog:** FAISS, BM25, CrossEncoder, evidence sufficiency validator, query rewriter, grounded generation endpoint, conversation history for RAG.

Ollama is used for **embeddings only**. Generation currently goes through **Gemini** (clinical summarize).

### Speech / IVR

- No STT, TTS, or telephony code in the working backend.
- `ai/speech`, `ai/ivr`, `storage/voice` are empty placeholders.
- Landing page *markets* IVR/voice; nothing is implemented.

### Tests

| Path | Coverage |
|------|----------|
| `backend/tests/test_super_admin.py` | RAG ingestion validation, embedding mocks, hospital scoping |
| `testing/**` | Empty |

### Config / deps

| Path | Notes |
|------|-------|
| `backend/requirements.txt` | fastapi, uvicorn, sqlalchemy, psycopg2, jose, passlib, dotenv, pydantic, pypdf, multipart — **no** faiss, bm25, sentence-transformers, cross-encoder, httpx for Ollama generate |
| `backend/.env.example` | DATABASE_URL, Supabase, Ollama embed settings |
| Root `.env.example` | Supabase URL/key only (legacy/next-style names) |

---

## 4. Frontend inventory

| Portal | Stack | Purpose today | GramSakhi fate |
|--------|-------|---------------|----------------|
| `landing_portal` | React/Vite/Tailwind | Sahyog healthcare marketing | **MODIFY** → GramSakhi home |
| `patient_portal` | React/Vite/Tailwind | Family/patient auth + dashboard | **MODIFY** → Citizen Ask GramSakhi / Conversation |
| `hospital_portal` | React/Vite/Tailwind | Doctor timeline, diagnosis, triage, hospital admin | **REMOVE** (or gut → unused) |
| `super_admin_portal` | React/Vite/Tailwind | Hospitals + Knowledge Base upload | **MODIFY** → Admin Dashboard / Document Management |
| `patient_app` | Flutter stub | Empty | **REMOVE** or leave unused |
| `frontend/shared` | Empty | — | **CREATE** shared UI only if needed |

### Super-admin reusable pieces

- Login + JWT guard
- Knowledge Base list/upload/detail (`KnowledgeBase.jsx`, `DocumentDetail.jsx`)
- Already includes category `GOVERNMENT_SCHEMES` among clinical categories
- Hospital manager UI — **REMOVE** in Phase 1+

### Hospital portal (healthcare UI to remove)

- Doctor dashboard, patient timeline, AI clinical summary panels
- Clinical triage / encounter
- Doctor / staff / department management

### Patient portal

- Auth (login/register/OTP/forgot password) infrastructure — **KEEP pattern**
- Family selector / patient dashboard — **REPLACE** with citizen chat UX

---

## 5. Database inventory

From `database/schemas/02_tables.sql` (35 tables conceptually):

### Healthcare-heavy (REMOVE / replace in domain redesign)

- hospitals, hospital_admins, departments, doctors
- doctor_availability, appointment_slots, appointments
- patients, patient_*, medical_history, medical_documents
- prescriptions, prescription_medicines, medicine_reminders*
- hospital_maps, navigation_*, landmarks
- notifications (appointment/medicine reminder types)

### Reusable / adapt

| Table | Fate |
|-------|------|
| `users` | **MODIFY** roles → ADMIN / CITIZEN (or session) |
| `user_sessions` | **KEEP** |
| `otp_verifications` | **KEEP** if phone OTP retained |
| `family_accounts` / `family_sessions` | **MODIFY** → citizen accounts OR replace with conversations |
| `chat_sessions` / `chat_messages` | **MODIFY** — schema exists but API not wired for GramSakhi; redesign off patient_id |
| `rag_documents` / `document_chunks` | **MODIFY** — add scheme metadata; vector strategy may move off pgvector to FAISS files |
| `audit_logs` / `activity_logs` | **KEEP** |

**Important:** Current RAG storage is **pgvector VECTOR(1024)** tied to Postgres. Target GramSakhi uses **FAISS + BM25 on disk** (see reference). Migration must decide: replace pgvector retrieval with FAISS/BM25 (preferred per architecture) while optionally keeping Postgres for users/docs metadata.

---

## 6. GramSakhi reference architecture (external)

Location: `C:\Users\tarun\Downloads\Gramasakhi`

Key modules to use as architectural reference (do not blindly copy-paste without adapting):

| Module | Role |
|--------|------|
| `document_store.py` | FAISS + BM25 + CrossEncoder + MMR |
| `retrieval_service.py` | Hybrid retrieve + CE thresholds |
| `evidence_validator.py` | SUPPORTED / UNSUPPORTED gate |
| `llm.py` | Ollama `/api/generate` + optional OpenAI |
| `query_rewriter.py` | Conversational follow-up → standalone query |
| `ingest_service.py` / `parse_utils.py` | PDF ingest, chunk, index |
| `chat.py` / `chat_prompt.py` | Conversation sessions |
| Frontend `pages/Ask.jsx`, `Chat.jsx`, `Documents.jsx`, `Upload.jsx` | Citizen + admin UX patterns |

Target LLM: **Ollama `llama3.2:3b`** at `http://localhost:11434/api/generate`.

---

## 7. Classification matrix

### KEEP

```text
KEEP — Infrastructure to preserve
---------------------------------
backend/app/main.py                    (FastAPI shell, CORS, startup hooks — rebrand)
backend/app/core/security.py           (JWT, bcrypt, OTP helpers)
backend/app/core/config.py             (Settings pattern — extend for GramSakhi)
backend/app/database/session.py        (SQLAlchemy session/engine)
backend/app/models/user.py             (User table concept)
backend/app/models/audit.py            (Audit logging concept)
backend/app/services/audit.py
backend/app/api/endpoints/auth.py      (auth patterns — strip hospital/patient specifics later)
backend/app/api/endpoints/super_admin.py  (auth + knowledge-base routes skeleton)
backend/app/services/rag.py            (extract/chunk/embed helpers — redesign retrieval)
backend/app/services/storage.py        (storage abstraction idea; may add local FS)
backend/app/models/rag.py              (document/chunk concepts)
frontend/*/vite + React + Tailwind stacks
frontend/super_admin_portal knowledge-base pages (adapt metadata)
frontend/*/AuthContext + api.js patterns
database connection / migration runner scripts
.gitignore
Ollama embedding connectivity pattern in main.py
backend/tests/test_super_admin.py      (adapt to new domain)
```

### MODIFY

```text
MODIFY — Domain / branding / architecture changes
-------------------------------------------------
PROJECT_NAME, README, landing copy: Sahyog Healthcare → GramSakhi
User roles: drop DOCTOR/HOSPITAL_ADMIN/PATIENT; keep ADMIN (+ citizen/session)
rag_documents: hospital_id → scheme metadata (scheme_name, ministry, state, category, source, language, …)
document_chunks: page/source provenance; stop depending solely on pgvector for retrieval
services/rag.py: align to FAISS + BM25 + CrossEncoder hybrid pipeline
super_admin KB UI: remove hospital scope; government scheme metadata + indexing status
patient_portal → citizen Ask / Conversation UI
landing_portal → GramSakhi voice-first governance landing
auth endpoints: citizen/session vs admin only
.env.example: OLLAMA_MODEL, OLLAMA_BASE_URL, STT/TTS/IVR providers, remove Gemini
requirements.txt: add faiss, rank_bm25, sentence-transformers, httpx/requests as needed
database schemas: redesign toward User, Scheme, Document, DocumentChunk, Conversation, Message
chat_sessions/chat_messages: detach from patients; add language, rewritten_query metadata
```

### REMOVE

```text
REMOVE — Healthcare domain (after dependency check in Phase 1)
--------------------------------------------------------------
API: patients, timeline, summarize (clinical)
Models: Patient*, Encounter*, Hospital*, Doctor*, Department*
Services: timeline, summarize, ai_summarizer, hospital
Providers: gemini_provider.py
Prompts/utils: summarize_prompt.py, summarize_formatter.py
Frontend: hospital_portal (entire clinical product surface)
Frontend hospital management in super_admin (HospitalList, HospitalDetail, Sidebar hospital nav)
Landing healthcare claims (AI Health Guidance, Nearby Hospitals, Aadhaar health data, etc.)
Storage folders: medical_documents, prescriptions (replace with government_documents)
Clinical categories in KB: CLINICAL_STANDARDS, PATIENT_GUIDANCE, HOSPITAL_OPERATIONS
SQL modules: appointments, prescriptions, medicine reminders, hospital maps/navigation
```

### CREATE

```text
CREATE — Required for GramSakhi (later phases)
----------------------------------------------
ai/rag/ or backend services:
  - faiss_store / document_store
  - bm25 index
  - cross_encoder reranker
  - hybrid retrieval service
  - evidence_validator
  - query_rewriter
  - llm.py (Ollama generate abstraction)
  - gramsakhi system prompt
API routes: /query, /chat, /conversations, /schemes, /documents, /voice, /stt, /tts, /ivr
Models: Scheme, Conversation, Message (or evolved chat_*)
Ingestion: OCR fallback, indexing status (Uploaded/Processing/Indexed/Failed)
Citizen UI: Ask GramSakhi (text + voice), scheme explorer, sources (doc + page)
Admin UI: document metadata form, reindex, status
STT/TTS abstractions + mocks until providers configured
IVR session abstraction + DTMF language menu + documented barge-in limitations
docs/: architecture, setup, RAG, IVR, migration tracker
docs/sahyog_to_gramsakhi_migration.md
Tests: retrieval, grounding, conversation rewrite, LLM offline, voice/IVR contracts
.env.example updates for GramSakhi
Sample government scheme PDFs for validation
```

### NEEDS REVIEW

```text
NEEDS REVIEW — Do not delete/replace without an explicit Phase decision
----------------------------------------------------------------------
1. Vector backend: keep Postgres pgvector as metadata+backup vs full cutover to FAISS files
   (Target architecture prefers FAISS; Sahyog already invested in pgvector.)
2. Supabase Storage dependency for RAG files vs local `storage/` / `uploads/`
3. family_accounts + OTP phone auth — reuse for citizens or replace with anonymous sessions + optional login
4. Flutter patient_app stub — delete vs ignore
5. Whether to merge Gramasakhi frontend into one portal vs keep dual citizen/admin apps
6. Embedding model: Sahyog uses mxbai-embed-large (1024); Gramasakhi uses multi-qa-mpnet-base-dot-v1
   — pick one and reindex; do not mix dimensions silently
7. Evidence validator: LLM-as-judge (Gramasakhi) vs score-threshold-only — retain LLM judge but fail closed
8. docker-compose.yml / LICENSE empty files — fill or remove
9. Existing SQLite sahyog.db / any local data — confirm before destructive migrations
10. google-genai / Gemini leftover deps if added outside requirements.txt
11. Chat tables exist in SQL but no ORM models/API — wire vs redesign
12. Web ingest from Gramasakhi (Karnataka/central portals) — optional Phase 2+ feature
```

---

## 8. Gap analysis vs target architecture

| Target capability | Sahyog today | Action |
|-------------------|--------------|--------|
| React citizen UI | Patient portal (healthcare) | Convert |
| Admin document mgmt | Super-admin KB (hospital-scoped) | Convert |
| FastAPI backend | Yes | Keep |
| Auth | Family + hospital + super-admin | Simplify to Admin + Citizen/session |
| PDF ingest + chunk + page meta | Partial (pypdf, page in chunk metadata) | Keep & extend (OCR) |
| Embeddings (Ollama) | Yes | Keep (decide model) |
| FAISS | No (pgvector instead) | Create / migrate from Gramasakhi |
| BM25 | No | Create |
| CrossEncoder | No | Create |
| Evidence sufficiency | No | Create |
| Grounded Ollama generation | No (Gemini clinical) | Create; remove Gemini path |
| Conversation + query rewrite | SQL stubs only | Create |
| STT / TTS | No | Create abstractions |
| IVR | No | Create abstractions |
| Vernacular (Kn/Hi/En) | Marketing only | Create + test before claiming |
| Government scheme metadata | Category enum includes GOVERNMENT_SCHEMES | Expand fields |
| Docs / tests for GramSakhi | Empty / RAG ingest tests only | Create |

---

## 9. Recommended phase plan (aligned to master prompt)

| Phase | Focus | Depends on |
|-------|-------|------------|
| **0** | This audit | — |
| **1** | Remove healthcare domain; keep app bootable | Audit |
| **2** | Government KB + ingestion metadata | Phase 1 |
| **3** | FAISS+BM25+CrossEncoder alignment | Phase 2 |
| **4** | Evidence sufficiency validator | Phase 3 |
| **5** | Ollama LLM + GramSakhi prompts | Phase 4 |
| **6** | Conversation + query rewriting | Phase 5 |
| **7** | STT/TTS vernacular pipeline | Phase 6 |
| **8** | IVR integration | Phase 7 |
| **9** | Integration / regression tests | Phase 8 |
| **10** | Documentation + cleanup | Phase 9 |

**Phase 1 critical path:** strip patient/timeline/summarize/hospital routers and UI so `uvicorn` and citizen/admin frontends start without healthcare imports; preserve auth + KB upload skeleton.

---

## 10. Risks

1. **Retrieval rewrite** is the largest technical risk (pgvector → hybrid FAISS/BM25/CE).
2. **Embedding model mismatch** will invalidate existing chunk vectors.
3. **Supabase requirement** may block local-only demos; need local storage fallback.
4. Empty `ai/` tree may tempt a parallel duplicate of `backend/app/services` — prefer one service layer under backend (or populate `ai/` carefully without duplication).
5. Claiming IVR/voice support before provider config would violate Rule 6.

---

## 11. Phase 0 deliverables checklist

- [x] Backend entry, routes, services, models, schemas, DB, auth inspected
- [x] Frontend portals and navigation inspected
- [x] Infrastructure / env / requirements inspected
- [x] Scaffold vs real code distinguished
- [x] GramSakhi reference located and mapped
- [x] KEEP / MODIFY / REMOVE / CREATE / NEEDS REVIEW produced
- [x] No major application code changes in Phase 0

---

## 12. Next phase

**PHASE 1 — Remove Healthcare Domain**

Start only after this audit is accepted. First actions:

1. Detach healthcare routers from `main.py`.
2. Remove or quarantine hospital/patient/timeline/summarize modules.
3. Rebrand project strings to GramSakhi.
4. Keep auth + super-admin knowledge-base boot path working.
5. Validate: backend starts, frontend(s) start, no broken imports.
