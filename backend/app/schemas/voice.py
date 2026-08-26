from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TranscribeResponse(BaseModel):
    success: bool
    text: Optional[str] = None
    original_transcript: Optional[str] = None
    normalized_transcript: Optional[str] = None
    detected_language: Optional[str] = None
    confidence: Optional[float] = None
    low_confidence: bool = False
    request_id: Optional[str] = None
    latency_ms: Optional[int] = None
    stt_model: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    response_language: str = Field(..., min_length=2, max_length=8)
    request_id: Optional[str] = None


class VoiceCitizenMessage(BaseModel):
    """Localized citizen-facing voice status/error strings."""

    key: str
    language: str
    message: str
