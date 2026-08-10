from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import json
import sys
import threading
import urllib.request

from app.core.config import settings
from app.database.session import engine, Base
from app.api.endpoints import auth, super_admin, chat

# Import active GramSakhi models so Base recognizes them before table creation
from app.models import family_account, user, rag, audit, conversation  # noqa: F401

# Ensure static directory exists
os.makedirs("static/uploads", exist_ok=True)

# Automatically create missing database tables on startup
if "pytest" not in sys.modules:
    _db_host = (
        settings.DATABASE_URL.split("@", 1)[1]
        if "@" in settings.DATABASE_URL
        else settings.DATABASE_URL
    )
    print(f"Database: {engine.dialect.name} -> {_db_host}", flush=True)
    if engine.dialect.name != "postgresql":
        print(
            "WARNING: Not using Supabase Postgres. Check DATABASE_URL in backend/.env "
            "and restart after killing any old uvicorn processes.",
            flush=True,
        )
    Base.metadata.create_all(bind=engine)
    try:
        from app.database.migrations.run_migrations import ensure_sqlite_columns

        ensure_sqlite_columns(engine)
    except Exception as e:
        print(f"Schema ensure skipped: {e}", flush=True)


def _check_ollama_connection() -> bool:
    try:
        url = f"{settings.OLLAMA_API_URL.rstrip('/')}/api/embed"
        payload = json.dumps({"model": settings.EMBEDDING_MODEL, "input": "ping"}).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            _ = json.loads(resp.read().decode("utf-8"))
        print("Ollama embedding service is reachable.", flush=True)
        return True
    except Exception as e:
        print(f"Failed to reach Ollama embedding service: {e}", flush=True)
        return False


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost:5176",
        "http://127.0.0.1:5176",
        "http://localhost:5177",
        "http://127.0.0.1:5177",
        "http://localhost:5178",
        "http://127.0.0.1:5178",
        "http://localhost:5179",
        "http://127.0.0.1:5179",
        "http://localhost:5180",
        "http://127.0.0.1:5180",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


def _warm_reranker() -> None:
    """Load the CrossEncoder off the request path so the first query isn't slow."""
    try:
        from app.services.cross_encoder import get_reranker

        get_reranker(settings.CROSS_ENCODER_MODEL).rerank(
            "warmup", [{"content": "warmup"}], top_k=1
        )
        print("CrossEncoder reranker warmed.", flush=True)
    except Exception as e:
        print(f"CrossEncoder warmup skipped: {e}", flush=True)


@app.on_event("startup")
async def startup_event():
    _check_ollama_connection()
    try:
        from app.background_jobs.web_ingest_scheduler import start_web_ingest_scheduler_if_enabled

        start_web_ingest_scheduler_if_enabled()
    except Exception as e:
        print(f"Web ingest scheduler not started: {e}", flush=True)

    if settings.HYBRID_RERANK_ENABLED:
        threading.Thread(target=_warm_reranker, daemon=True).start()


app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(chat.router, prefix=f"{settings.API_V1_STR}/chat", tags=["chat"])
app.include_router(super_admin.router, prefix="/api/v1/super-admin", tags=["admin"])


@app.get("/")
def read_root():
    return {
        "message": "Welcome to GramSakhi API",
        "project": "GramSakhi: RAG-Based Vernacular GenAI LLM + IVR System for Last-Mile Governance",
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "gramsakhi"}


@app.get("/health/db")
def db_health():
    """Report which database the live process is actually using."""
    from sqlalchemy import text
    from app.database.session import engine

    url = settings.DATABASE_URL
    dialect = engine.dialect.name
    host = "sqlite"
    if "@" in url:
        host = url.split("@", 1)[1]
    elif url.startswith("sqlite"):
        host = url

    ok = False
    detail = None
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            ok = True
    except Exception as e:  # noqa: BLE001
        detail = f"{type(e).__name__}: {e}"

    return {
        "ok": ok,
        "dialect": dialect,
        "using_supabase_postgres": dialect == "postgresql" and "supabase.co" in url,
        "host": host,
        "detail": detail,
    }


@app.get("/health/ollama")
def ollama_health():
    reachable = _check_ollama_connection()
    llm_status = {}
    try:
        from app.services.llm_service import check_ollama_llm

        llm_status = check_ollama_llm()
    except Exception as e:  # noqa: BLE001
        llm_status = {
            "ollama_available": False,
            "model_available": False,
            "detail": f"{type(e).__name__}: {e}",
        }
    return {
        "ollama_reachable": reachable,
        "embedding_reachable": reachable,
        "ollama_available": llm_status.get("ollama_available", reachable),
        "model_available": llm_status.get("model_available", False),
        "llm_model": llm_status.get("model"),
        "detail": llm_status.get("detail"),
    }


@app.get("/health/supabase")
def supabase_health():
    from app.services.storage import check_supabase_connection

    return check_supabase_connection()
