# GramSakhi — Demo Day Checklist

Use `http://127.0.0.1` for all URLs (avoid mixing with `localhost` on Windows).

## Pre-flight

- [ ] Supabase Postgres (`GET /health/db` → postgresql)
- [ ] Ollama running (`nomic-embed-text`, `llama3.2:3b`)
- [ ] Whisper / faster-whisper import OK
- [ ] TTS (edge-tts) OK
- [ ] Playwright Chromium installed (for live SPA)
- [ ] Backend on :8000
- [ ] Unified frontend on :5173 (`frontend/gramsakhi`)
- [ ] Demo data (PM-KISAN, Shakti, PMFBY, Gruha Lakshmi, Anna Bhagya) present  
      (`python scripts/seed_demo_schemes.py` if Shakti/PMFBY missing)
- [ ] Indexes present (`backend/indexes/` FAISS + BM25; rebuild after seed)
- [ ] `python scripts/gramsakhi_system_check.py` overall PASS (or note known soft fails)

## Flows

- [ ] Login (OTP appears in API terminal)
- [ ] English: “What is PM-KISAN?”
- [ ] Kannada: “ಶಕ್ತಿ ಯೋಜನೆಗೆ ಯಾರು ಅರ್ಹರು?”
- [ ] Hindi: “पीएम किसान योजना के लिए कौन पात्र है?”
- [ ] Voice (EN / KN / HI) + TTS playback
- [ ] Live retrieval (if demoing) + second-request reuse
- [ ] Chat history: New Chat → switch back → no context leak
- [ ] Admin: Knowledge Base list + Registry page

## Mentor talking points

1. Evidence Validator blocks hallucination  
2. Knowledge-first; live government only on FAIL  
3. myScheme trusted; outbound links re-checked  
4. One unified chat — language auto-detected  
5. Shared government KB; private conversations  

## If something fails live

| Failure | What to say / do |
|---------|------------------|
| Ollama down | Show `/health/system`; text pipeline cannot invent answers |
| Live CAPTCHA / timeout | Show official link guidance — by design |
| STT/TTS down | Continue with typed chat |
| Wrong host | Restart portals on `127.0.0.1` |
