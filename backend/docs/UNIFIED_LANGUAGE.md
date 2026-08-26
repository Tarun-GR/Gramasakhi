# Unified Multilingual Chat + Voice

Language is a **per-message** property. One conversation can switch EN ↔ KN ↔ HI freely.

## Canonical resolver

`language_service.resolve_response_language()` is the single source of truth for text and voice.

Priority:

1. Explicit instruction in the current message  
2. Unicode script in the current message  
3. Lexical English cues (Latin questions; scheme names alone do not count)  
4. STT language (ignored when it conflicts with clear English lexical cues)  
5. Conversation last-language (fallback only)  
6. Previous response language  
7. Weak UI preference (currently unused for answer language)  
8. Default EN  

`conversation.language` stores the last detected language for weak fallback — it is **not** a lock.

## Frontend

- One chat, one microphone  
- Language chip is informational (detected), not a mode selector  
- Chat requests do not send a language lock  

## Generation

Bounded regen via `MAX_LANGUAGE_REGEN_ATTEMPTS` remains. Controlled failures stay in the target language (no silent English fallback).
