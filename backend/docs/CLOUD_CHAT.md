# Cloud chat latency (Render)

## Verified production signal

`GET https://gramasakhi.onrender.com/health/system` reports **FAISS/BM25 missing** under `/opt/render/project/src/backend/indexes` (ephemeral disk). Chat used to call `build_all()` on first message (heavy) and could run **live government fallback up to 240s**, exceeding Render’s ~**100s** HTTP proxy → **502** with only a slow or absent `POST /api/chat` in logs.

## Code behavior (after fix)

| Stage | Cloud behavior |
|-------|----------------|
| Retrieval | **Pgvector-first** when disk indexes absent; no synchronous full index rebuild on chat |
| Live gov | Capped by `CLOUD_LIVE_GOV_OVERALL_CAP_SECONDS` (default 45) and remaining chat budget |
| Chat HTTP | Budget ~88s (`CHAT_PIPELINE_BUDGET_SECONDS=0` auto) → **504 JSON** instead of hanging |
| Logs | `chat_http_start/end`, `chat_stage`, `chat_retrieval`, `chat_complete` (no message bodies) |

## Recommended Render env

```
RUNTIME_PROFILE=cloud
LLM_PROVIDER=gemini
EMBEDDING_PROVIDER=gemini
LLM_FALLBACK_TO_OLLAMA=false
STARTUP_WARM_CROSS_ENCODER=false
LIVE_GOV_BROWSER_ENABLED=false
CLOUD_LIVE_GOV_OVERALL_CAP_SECONDS=45
CHAT_PIPELINE_BUDGET_SECONDS=0
```

Optional: attach a **persistent disk** at `backend/indexes` and run `scripts/rebuild_hybrid_indexes.py` (or ingest pipeline) once so hybrid FAISS+BM25 is used.

## Do not use on Render

- `OLLAMA_*` for LLM/embeddings (laptop Ollama is not reachable)
- `LIVE_GOV_OVERALL_TIMEOUT_SECONDS=240` without cap (proxy will still 502)
