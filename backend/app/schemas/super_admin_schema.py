from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Any, Dict
from uuid import UUID
from datetime import datetime


class SuperAdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserMiniResponse(BaseModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    role: str


class SuperAdminTokenResponse(BaseModel):
    accessToken: str
    user: UserMiniResponse


class DashboardSummaryResponse(BaseModel):
    total_documents: int
    indexed_documents: int
    processing_documents: int
    failed_documents: int


class KnowledgeDocumentDetailResponse(BaseModel):
    id: UUID
    uploaded_by: Optional[UUID] = None
    uploader_name: Optional[str] = None
    title: str
    file_url: str
    category: str
    version: str
    scheme_name: Optional[str] = None
    ministry: Optional[str] = None
    state: Optional[str] = None
    source: Optional[str] = None
    language: Optional[str] = None
    document_type: Optional[str] = None
    indexing_status: str = "INDEXED"
    created_at: datetime
    updated_at: datetime
    chunk_count: int = 0

    class Config:
        from_attributes = True


class KnowledgeDocumentListResponse(BaseModel):
    items: List[KnowledgeDocumentDetailResponse]
    page: int
    limit: int
    total: int
    total_pages: int


class WebIngestRequest(BaseModel):
    """Admin trigger for government website ingestion."""

    source: str = Field(
        ...,
        description="GOV source id: 'central' | 'karnataka' | catalog scheme id (e.g. pm-kisan)",
    )
    query: Optional[str] = Field(
        None, description="Optional keyword filter within the selected source"
    )
    urls: Optional[List[str]] = Field(
        None, description="Optional explicit allowlisted URLs to ingest"
    )
    max_docs: int = Field(5, ge=1, le=20)
    crawl_links: bool = Field(
        False, description="If true, follow PDF links discovered on HTML pages"
    )


class WebIngestResponse(BaseModel):
    source: str
    query: Optional[str] = None
    summary: Dict[str, Any]
    results: List[Dict[str, Any]]
