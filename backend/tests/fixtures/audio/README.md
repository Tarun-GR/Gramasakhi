# Voice test fixtures

Deterministic synthetic WAVs for STT validation tests (silence, tone).
Speech recognition accuracy tests use mocked STT hooks in 	ests/test_voice.py
so CI does not require a microphone or downloaded Whisper weights.

For manual acceptance with real speech, record short clips locally:
- kn_pmkisan.webm — Kannada + PM-KISAN
- hi_eligibility.webm — Hindi
- en_eligibility.webm — English
Do not commit private citizen recordings.
