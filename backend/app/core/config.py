from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load backend/.env regardless of process cwd (uvicorn reloader, tests, etc.)
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
# Force-load into os.environ so SQLAlchemy / subprocesses see the same values.
# override=True beats empty or stale shell vars that otherwise pin SQLite.
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=True)


class Settings(BaseSettings):
    PROJECT_NAME: str = "GramSakhi API"
    API_V1_STR: str = "/api"
    SECRET_KEY: str = "sahyog_very_secret_key_change_me_in_production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Loaded from backend/.env — falls back to local SQLite if not set
    DATABASE_URL: str = "sqlite:///./gramsakhi.db"

    # Supabase Storage Configurations for RAG Guideline Documents
    SUPABASE_URL: str = ""
    # New-style publishable key (sb_publishable_...) or legacy anon JWT
    SUPABASE_PUBLISHABLE_KEY: str = ""
    # Secret / service_role key required for private bucket writes
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "rag-documents"

    # Embedding Configurations
    EMBEDDING_PROVIDER: str = "ollama"
    EMBEDDING_MODEL: str = "mxbai-embed-large"
    EMBEDDING_DIMENSIONS: int = 1024
    # Shared Ollama host (embeddings + legacy callers)
    OLLAMA_API_URL: str = "http://localhost:11434"
    # Phase 5 generation — prefer OLLAMA_BASE_URL; falls back to OLLAMA_API_URL in llm_service
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_LLM_MODEL: str = "llama3.2:3b"
    # Backward-compatible alias used in some .env files
    OLLAMA_MODEL: str = "llama3.2:3b"
    OLLAMA_LLM_TEMPERATURE: float = 0.1
    OLLAMA_LLM_TIMEOUT_SECONDS: float = 60.0
    OLLAMA_LLM_NUM_PREDICT: int = 512

    # Phase 6 — conversation memory + query rewriting
    CONVERSATION_HISTORY_LIMIT: int = 6
    QUERY_REWRITE_USE_OLLAMA: bool = False
    QUERY_REWRITE_TIMEOUT_SECONDS: float = 15.0

    # Live government retrieval fallback (only when indexed evidence is insufficient)
    LIVE_GOV_FALLBACK_ENABLED: bool = True
    LIVE_GOV_MAX_SOURCES: int = 4
    LIVE_GOV_MAX_CANDIDATES: int = 8
    LIVE_GOV_MAX_PDFS: int = 2
    LIVE_GOV_MAX_PDF_SIZE_MB: float = 10.0
    LIVE_GOV_TIMEOUT_SECONDS: float = 25.0
    LIVE_GOV_OVERALL_TIMEOUT_SECONDS: float = 240.0

    # Hybrid RAG (FAISS + BM25 + CrossEncoder)
    HYBRID_INDEX_DIR: str = "indexes"
    HYBRID_FAISS_WEIGHT: float = 0.6
    HYBRID_BM25_WEIGHT: float = 0.4
    HYBRID_CANDIDATE_K: int = 20
    HYBRID_TOP_K: int = 5
    HYBRID_RERANK_ENABLED: bool = True
    CROSS_ENCODER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Evidence sufficiency hard gate (Phase 4)
    EVIDENCE_RELEVANCE_THRESHOLD: float = 0.65
    EVIDENCE_COVERAGE_THRESHOLD: float = 0.6
    EVIDENCE_AGREEMENT_THRESHOLD: float = 0.7
    EVIDENCE_AGREEMENT_VARIANCE_MAX: float = 0.08
    EVIDENCE_MIN_QUERY_TERMS: int = 2
    EVIDENCE_GATE_ENABLED: bool = True
    # Chunks scoring below this are dropped before validation so weak tail hits
    # cannot drag down (or pad) the evidence set.
    EVIDENCE_DOC_FLOOR: float = 0.5
    # Cache query embeddings — repeated citizen questions are common.
    QUERY_EMBED_CACHE_SIZE: int = 256

    # CORS Allowed origins
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000"
    ]

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        # Empty OS env vars (common in IDE shells) must not override .env values
        env_ignore_empty=True,
    )


settings = Settings()
