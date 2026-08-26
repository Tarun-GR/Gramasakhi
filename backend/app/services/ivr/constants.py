"""IVR-A1 constants — language mapping and speech prompts."""

from __future__ import annotations

SUPPORTED_LANGUAGES = frozenset({"kn", "hi", "en"})

DIGIT_TO_LANGUAGE: dict[str, str] = {
    "1": "kn",
    "2": "hi",
    "3": "en",
}

LANGUAGE_CONFIRMATION: dict[str, str] = {
    "kn": "Kannada selected.",
    "hi": "Hindi selected.",
    "en": "English selected.",
}

MENU_PROMPT = (
    "Welcome to GramSakhi. For Kannada, press 1. For Hindi, press 2. For English, press 3."
)

INVALID_PROMPT = (
    "Invalid choice. Please press 1 for Kannada, 2 for Hindi, or 3 for English."
)

GOODBYE_PROMPT = "Sorry, we could not understand your choice. Goodbye."

# Bounded retries for invalid digits and no-input (timeout) on the application side.
MAX_RETRY_ATTEMPTS = 2

GATHER_INPUT_TIMEOUT_SECONDS = 5
GATHER_REPEAT_MENU = 2
GATHER_MAX_INPUT_DIGITS = 1
GATHER_FINISH_ON_KEY = ""

# IVR session language (kn/hi/en) → GramSakhi STT language_hint (KN/HI/EN)
IVR_TO_STT_LANGUAGE: dict[str, str] = {
    "kn": "KN",
    "hi": "HI",
    "en": "EN",
}

# A2 STT telephony prompts (no transcript echoed to caller)
STT_SUCCESS_PROMPT = "Thank you. I received your message."
STT_LOW_CONFIDENCE_PROMPT = "I couldn't clearly understand that. Please try again."
STT_EMPTY_PROMPT = "I couldn't clearly understand that. Please try again."
STT_UNAVAILABLE_PROMPT = "Sorry, speech recognition is unavailable right now."
STT_GOODBYE_PROMPT = "Sorry, we could not understand your speech. Goodbye."

MAX_STT_RETRY_ATTEMPTS = 2

# A3 — chat/RAG (IVR session language → /api/chat language field)
IVR_TO_CHAT_LANGUAGE: dict[str, str] = {
    "kn": "KN",
    "hi": "HI",
    "en": "EN",
}

MAX_IVR_TRANSCRIPTION_LENGTH = 8000

CHAT_UNAVAILABLE_PROMPT = (
    "Sorry, GramSakhi could not complete your request right now. Please try again later."
)
CHAT_MISSING_TRANSCRIPTION_PROMPT = (
    "Sorry, we did not receive your message. Please speak again."
)

# A4 — TTS playback (matches SynthesizeRequest.text max_length)
IVR_TO_TTS_LANGUAGE: dict[str, str] = IVR_TO_CHAT_LANGUAGE
MAX_IVR_TTS_TEXT_LENGTH = 5000
IVR_SUPPORTED_AUDIO_MIME = frozenset({"audio/mpeg", "audio/mp3"})

TTS_UNAVAILABLE_PROMPT = "Sorry, voice playback is unavailable right now."
TTS_MISSING_RESPONSE_PROMPT = "Sorry, there is no response to play yet."
TTS_RESPONSE_TOO_LONG_PROMPT = "Sorry, the response is too long to play on this call."

# A5 — multi-turn loop
CONTINUE_MENU_PROMPT = (
    "Press 1 to ask another question. Press 2 to end the call."
)
CONTINUE_INVALID_PROMPT = (
    "Invalid choice. Press 1 to ask another question, or 2 to end the call."
)
CONTINUE_GOODBYE_PROMPT = "Thank you for calling GramSakhi. Goodbye."
TURN_LIMIT_PROMPT = "You have reached the maximum number of questions for this call. Goodbye."
SILENCE_FIRST_PROMPT = "Sorry, I didn't hear anything. Please try again."
SILENCE_GOODBYE_PROMPT = "Let's end the call. Goodbye."
CHAT_FAILURE_RETRY_PROMPT = (
    "Sorry, I'm unable to answer right now. Please try again later."
)
CHAT_FAILURE_GOODBYE_PROMPT = (
    "Sorry, I'm unable to answer right now. Goodbye."
)
TTS_FAILURE_RETRY_PROMPT = "Sorry, I cannot play the answer right now. Please try again."
TTS_FAILURE_GOODBYE_PROMPT = "Sorry, I cannot play the answer right now. Goodbye."
IVR_BUSY_PROMPT = "Please wait while your previous request is processed."

DIGIT_CONTINUE = "1"
DIGIT_END = "2"

MAX_CONTINUE_RETRY_ATTEMPTS = 2
MAX_SILENCE_ATTEMPTS = 2
MAX_CHAT_RETRY_ATTEMPTS = 2
MAX_TTS_RETRY_ATTEMPTS = 2
