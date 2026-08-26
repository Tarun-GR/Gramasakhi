# Multilingual Speech + Retrieval Hardening

Voice and KN/HI text use an **adapter bridge** around the existing hybrid RAG pipeline.
FAISS / BM25 / CrossEncoder / Evidence Validator / live government / Ollama were not redesigned.

## Flow

```
citizen query (KN/HI/EN) or STT transcript
  → query rewriter (follow-ups → standalone; may produce EN retrieval form)
  → multilingual_retrieval_service.build_retrieval_plan
       original + normalized + English semantic/keyword queries
  → multi_query_hybrid_retrieve (existing hybrid_retrieve × queries → merge → CE)
  → EvidenceValidator(validation_query = English semantic when expanded)
  → live gov uses live_search_query (English discovery) on FAIL
  → LLM answers in response_language (KN/HI/EN)
  → language quality gate
  → optional TTS(response_language)
```

Citizen-visible text is never rewritten by the bridge.

## STT

- Engine: `faster-whisper` / Whisper `base` (CPU int8)
- Always `task=transcribe` (never translate)
- `language_hint` soft prior; Unicode script overrides wrong STT tags
- `original_transcript` + `normalized_transcript` (whitespace only)

WER on real speech was not CI-measured (no private citizen recordings). Keep `base` until a local A/B vs `small` shows a clear KN/HI gain worth the latency/RAM cost.

## Config

Uses existing Phase 7 STT/TTS settings. No new required env vars.
