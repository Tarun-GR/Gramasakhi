"""IVR-A1 schemas — Exotel Gather request parameters and JSON response."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class GatherPromptText(BaseModel):
    text: str = Field(..., min_length=1, description="Speech-friendly prompt text for Exotel TTS.")


class IvrGatherResponse(BaseModel):
    """Exotel Gather application URL JSON contract (supported fields only)."""

    gather_prompt: GatherPromptText
    max_input_digits: int = Field(default=1, ge=1, le=1)
    finish_on_key: str = ""
    input_timeout: int = Field(default=5, ge=1, le=60)
    repeat_menu: int = Field(default=2, ge=0, le=5)
    repeat_gather_prompt: Optional[GatherPromptText] = None


class IvrLanguageQuery(BaseModel):
    """Documented Exotel query parameters for OpenAPI (/docs)."""

    CallSid: str = Field(..., min_length=1, description="Exotel call identifier (required session key).")
    digits: Optional[str] = Field(
        default=None,
        description='DTMF digit(s) from Gather; may include surrounding quotes from Exotel.',
    )
    CallFrom: Optional[str] = Field(default=None, description="Caller number (logged masked only).")
    CallTo: Optional[str] = Field(default=None, description="Called Exotel number.")
    From: Optional[str] = Field(default=None, description="Alias for caller number in some Exotel payloads.")
    To: Optional[str] = Field(default=None, description="Alias for called number in some Exotel payloads.")


class IvrTranscribeResponse(BaseModel):
    """IVR-A2 STT outcome for Exotel Flow playback (transcript stored server-side only)."""

    gather_prompt: GatherPromptText
    success: bool = False
    low_confidence: bool = False


class IvrChatRequest(BaseModel):
    """IVR-A3 chat request — language/conversation derived server-side from CallSid session."""

    CallSid: str = Field(..., min_length=1, description="Exotel call identifier (required).")
    transcription: Optional[str] = Field(
        default=None,
        max_length=8000,
        description="Citizen message text from A2 STT. If omitted, uses session transcription.",
    )
    # Ignored if present — never authoritative
    language: Optional[str] = Field(default=None, description="Ignored — derived from A1 session.")
    lang: Optional[str] = Field(default=None, description="Ignored — derived from A1 session.")
    conversation_id: Optional[str] = Field(default=None, description="Ignored — server-managed.")
    account_id: Optional[str] = Field(default=None, description="Ignored — server-managed.")
    citizen_id: Optional[str] = Field(default=None, description="Ignored — server-managed.")


class IvrChatResponse(BaseModel):
    """IVR-A3 normalized chat/RAG outcome (no JWT, no raw transcript echo)."""

    call_sid: str
    language: str = Field(description="A1 IVR session language code: kn | hi | en")
    conversation_id: str
    response_text: str
    evidence_status: str = Field(description="SUPPORTED | PARTIAL | UNSUPPORTED")
    sources: list[dict[str, Any]] = Field(default_factory=list)
    response_language: Optional[str] = None
    success: bool = True


class IvrTtsRequest(BaseModel):
    """IVR-A4 TTS request — response text from A3 session only."""

    CallSid: str = Field(..., min_length=1)
    response_text: Optional[str] = Field(
        default=None,
        description="Ignored — server uses A3 session response text.",
    )
    language: Optional[str] = Field(default=None, description="Ignored — derived from session.")
    lang: Optional[str] = Field(default=None, description="Ignored — derived from session.")


class IvrExotelPlayback(BaseModel):
    playback_to: str = "both"
    type: str = "audio_url"
    value: str


class IvrTtsResponse(BaseModel):
    call_sid: str
    language: str
    success: bool = False
    audio_url: Optional[str] = None
    start_call_playback: Optional[IvrExotelPlayback] = None
    mime_type: Optional[str] = None
    message: Optional[str] = None


class IvrContinueRequest(BaseModel):
    """IVR-A5 continue/end DTMF — language and conversation derived server-side."""

    CallSid: str = Field(..., min_length=1)
    digits: Optional[str] = Field(
        default=None,
        description="DTMF: 1=continue, 2=end. May be quoted by Exotel.",
    )
    language: Optional[str] = Field(default=None, description="Ignored — derived from session.")
    conversation_id: Optional[str] = Field(default=None, description="Ignored — server-managed.")


class IvrContinueResponse(BaseModel):
    gather_prompt: GatherPromptText
    end_call: bool = False
    continue_loop: bool = False
    success: bool = True

