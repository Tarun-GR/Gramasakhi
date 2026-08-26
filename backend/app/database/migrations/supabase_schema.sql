-- GramSakhi — Supabase Postgres schema
-- Citizen accounts use physical table name family_accounts (compatibility; see docs/LEGACY_COMPATIBILITY.md).
-- Run in: Supabase Dashboard → SQL Editor → New query → Run
-- Project: jrhnkjpmpxozsildgonr

-- 1) Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- 2) Admin users
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  first_name VARCHAR(100) NOT NULL,
  last_name VARCHAR(100) NOT NULL,
  phone_number VARCHAR(20),
  role VARCHAR(50) NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ
);

-- 3) Citizen accounts (physical table name family_accounts; see docs/LEGACY_COMPATIBILITY.md)
CREATE TABLE IF NOT EXISTS family_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_number VARCHAR(20) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(150),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS family_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_account_id UUID NOT NULL REFERENCES family_accounts(id) ON DELETE CASCADE,
  refresh_token VARCHAR(500) NOT NULL UNIQUE,
  ip_address VARCHAR(45),
  user_agent TEXT,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS otp_verifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_number VARCHAR(20) NOT NULL,
  otp_hash VARCHAR(255) NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  verified BOOLEAN NOT NULL DEFAULT FALSE,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4) Knowledge base (government scheme PDFs live as files in Storage;
--    metadata + chunks live here)
CREATE TABLE IF NOT EXISTS rag_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hospital_id UUID,
  uploaded_by UUID REFERENCES users(id) ON DELETE SET NULL,
  title VARCHAR(255) NOT NULL,
  file_url TEXT NOT NULL,
  category VARCHAR(100) NOT NULL,
  version VARCHAR(50) NOT NULL DEFAULT '1.0',
  scheme_name VARCHAR(255),
  ministry VARCHAR(255),
  state VARCHAR(100),
  source VARCHAR(255),
  language VARCHAR(20),
  document_type VARCHAR(100),
  indexing_status VARCHAR(50) NOT NULL DEFAULT 'INDEXED',
  document_hash VARCHAR(64),
  last_ingested_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_rag_documents_document_hash
  ON rag_documents (document_hash);

-- IMPORTANT: vector size must match EMBEDDING_DIMENSIONS in backend/.env
-- Current local demo uses nomic-embed-text → 768
-- If you switch to mxbai-embed-large, use vector(1024) instead and re-ingest
CREATE TABLE IF NOT EXISTS document_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  embedding vector(768) NOT NULL,
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id
  ON document_chunks (document_id);

-- Optional: speed up pgvector similarity (after you have some rows)
-- CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding
--   ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- 5) Chat history
CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  citizen_account_id UUID REFERENCES family_accounts(id) ON DELETE SET NULL,
  language VARCHAR(20) DEFAULT 'en',
  title VARCHAR(255),
  active_scheme_context VARCHAR(255),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  deleted_at TIMESTAMPTZ,
  last_message_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role VARCHAR(20) NOT NULL,
  content TEXT NOT NULL,
  rewritten_query TEXT,
  language VARCHAR(20),
  evidence_status VARCHAR(20),
  input_mode VARCHAR(20),
  knowledge_source VARCHAR(50),
  sources_json TEXT,
  official_sources_json TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6) Audit
CREATE TABLE IF NOT EXISTS audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  action VARCHAR(50) NOT NULL,
  table_name VARCHAR(100) NOT NULL,
  record_id UUID NOT NULL,
  old_values JSONB,
  new_values JSONB,
  ip_address VARCHAR(45),
  user_agent TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS activity_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  activity_type VARCHAR(100) NOT NULL,
  description TEXT,
  metadata JSONB,
  ip_address VARCHAR(45),
  user_agent TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 8) Row Level Security — deny-by-default for PostgREST/anon.
-- FastAPI connects as the table owner (DATABASE_URL) and is not subject to
-- RLS unless FORCE ROW LEVEL SECURITY is set. Do not add "allow all" policies.
DO $$
DECLARE
  t text;
  tables text[] := ARRAY[
    'users',
    'family_accounts',
    'family_sessions',
    'otp_verifications',
    'rag_documents',
    'document_chunks',
    'conversations',
    'messages',
    'audit_logs',
    'activity_logs'
  ];
BEGIN
  FOREACH t IN ARRAY tables LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    END IF;
  END LOOP;
END $$;

DO $$
BEGIN
  REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
  REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
EXCEPTION
  WHEN undefined_object THEN
    NULL;
END $$;
