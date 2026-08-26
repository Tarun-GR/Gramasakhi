from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timezone
from app.database.session import Base


def generate_uuid():
    return str(uuid.uuid4())


class Conversation(Base):
    """Citizen conversation session."""

    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    citizen_account_id = Column(
        UUID(as_uuid=False),
        ForeignKey("family_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    language = Column(String(20), nullable=True, default="en")
    title = Column(String(255), nullable=True)
    active_scheme_context = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    messages = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    """Single turn in a conversation (user query or assistant response)."""

    __tablename__ = "messages"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    conversation_id = Column(
        UUID(as_uuid=False),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(20), nullable=False)  # user | assistant | system
    content = Column(Text, nullable=False)
    rewritten_query = Column(Text, nullable=True)
    language = Column(String(20), nullable=True)
    evidence_status = Column(String(20), nullable=True)  # SUPPORTED | UNSUPPORTED | None
    input_mode = Column(String(20), nullable=True)  # text | voice
    knowledge_source = Column(String(50), nullable=True)
    sources_json = Column(Text, nullable=True)  # JSON-serialized sources list
    official_sources_json = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    conversation = relationship("Conversation", back_populates="messages")
