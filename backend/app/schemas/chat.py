from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: Optional[Union[str, UUID]] = None
    language: Optional[str] = None


class ChatResponse(BaseModel):
    conversation_id: Union[str, UUID]
    created_new_conversation: bool = False
    message_id: Optional[Union[str, UUID]] = None
    assistant_message_id: Optional[Union[str, UUID]] = None
    original_query: str
    rewritten_query: Optional[str] = None
    was_rewritten: bool = False
    answer: str
    confidence: Optional[str] = None
    reason: Optional[str] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    validated: bool = False
    llm_invoked: bool = False
    knowledge_source: Optional[str] = None
    live_status: Optional[str] = None
    active_scheme_context: Optional[str] = None
    error: Optional[str] = None


class ConversationMessageOut(BaseModel):
    id: Union[str, UUID]
    role: str
    content: str
    rewritten_query: Optional[str] = None
    evidence_status: Optional[str] = None
    created_at: Optional[str] = None


class ConversationHistoryResponse(BaseModel):
    conversation_id: Union[str, UUID]
    messages: List[ConversationMessageOut]
    active_scheme_context: Optional[str] = None
