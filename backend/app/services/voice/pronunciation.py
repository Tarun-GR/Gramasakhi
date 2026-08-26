"""Optional TTS pronunciation helpers — never mutate display_text."""

from __future__ import annotations

import re
from typing import Tuple


def build_tts_text(display_text: str, language: str) -> Tuple[str, str]:
    """
    Returns (display_text, tts_text).

    display_text is unchanged. tts_text may soften URLs for speech only.
    Numbers and scheme identities are preserved.
    """
    display = display_text or ""
    tts = display
    # Speak hostnames instead of full URLs (display unchanged)
    def _url_speak(m: re.Match) -> str:
        url = m.group(0)
        host = re.sub(r"^https?://", "", url).split("/")[0]
        return host or "website"

    tts = re.sub(r"https?://[^\s<>\"')\]]+", _url_speak, tts)
    # Light spacing for currency for clearer speech
    tts = re.sub(r"\u20b9\s*", "rupees ", tts)
    tts = re.sub(r"\bRs\.?\s*", "rupees ", tts, flags=re.I)
    return display, tts.strip()
