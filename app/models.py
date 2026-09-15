from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .core import settings

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None

EmbeddingType = Vector(1536) if Vector is not None and settings.database_url.startswith("postgres") else JSON


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(24), default="requester")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text)
    requester_email: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(64), default="General")
    priority: Mapped[str] = mapped_column(String(24), default="Medium")
    status: Mapped[str] = mapped_column(String(24), default="Open")
    assignee: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="AI Agent")
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_approval: Mapped[bool] = mapped_column(default=False)
    safety_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(180), nullable=True)
    resolution_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parent_ticket_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    related_ticket_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    watchers: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    title: Mapped[str] = mapped_column(String(220))
    category: Mapped[str] = mapped_column(String(64), default="General", index=True)
    source: Mapped[str] = mapped_column(String(120), default="Uploaded runbook")
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    min_role: Mapped[str] = mapped_column(String(24), default="requester")
    status: Mapped[str] = mapped_column(String(24), default="indexed")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(180), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType, nullable=True)
    chunk_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_name: Mapped[str] = mapped_column(String(120), default="Alex Morgan")
    user_email: Mapped[str] = mapped_column(String(180), default="alex.morgan@acme.co")
    status: Mapped[str] = mapped_column(String(24), default="Open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(24))
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TicketEvent(Base):
    __tablename__ = "ticket_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(120), default="Relay AI")
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    visibility: Mapped[str] = mapped_column(String(16), default="internal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    storage_path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AgentFeedback(Base):
    __tablename__ = "agent_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    ticket_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rating: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(180), unique=True, nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    if settings.database_url.startswith("postgres"):
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=engine)
    # Keep the demo self-healing when an existing local SQLite database predates
    # the escalation fields. Production deployments should use Alembic migrations.
    with engine.begin() as connection:
        if settings.database_url.startswith("sqlite"):
            existing = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(tickets)").fetchall()}
            columns = {
                "requester_email": "VARCHAR(180)",
                "sla_due_at": "DATETIME",
                "escalated_at": "DATETIME",
                "escalation_reason": "TEXT",
                "external_provider": "VARCHAR(32)",
                "external_id": "VARCHAR(120)",
                "external_url": "VARCHAR(500)",
                "last_synced_at": "DATETIME",
                "sync_error": "TEXT",
                "requires_approval": "BOOLEAN DEFAULT 0",
                "safety_flags": "JSON",
                "approved_at": "DATETIME",
                "approved_by": "VARCHAR(180)",
                "resolution_code": "VARCHAR(64)",
                "resolved_at": "DATETIME",
                "closed_at": "DATETIME",
                "reopened_at": "DATETIME",
                "parent_ticket_id": "INTEGER",
                "duplicate_of_id": "INTEGER",
                "related_ticket_ids": "JSON",
                "watchers": "JSON",
            }
            for name, column_type in columns.items():
                if name not in existing:
                    connection.exec_driver_sql(f"ALTER TABLE tickets ADD COLUMN {name} {column_type}")
            event_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(ticket_events)").fetchall()}
            if "visibility" not in event_columns:
                connection.exec_driver_sql("ALTER TABLE ticket_events ADD COLUMN visibility VARCHAR(16) DEFAULT 'internal'")
        else:
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS requester_email VARCHAR(180)")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS sla_due_at TIMESTAMP WITH TIME ZONE")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMP WITH TIME ZONE")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS escalation_reason TEXT")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS external_provider VARCHAR(32)")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS external_id VARCHAR(120)")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS external_url VARCHAR(500)")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP WITH TIME ZONE")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS sync_error TEXT")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS requires_approval BOOLEAN DEFAULT FALSE")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS safety_flags JSONB")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS approved_by VARCHAR(180)")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS resolution_code VARCHAR(64)")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP WITH TIME ZONE")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP WITH TIME ZONE")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS reopened_at TIMESTAMP WITH TIME ZONE")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS parent_ticket_id INTEGER")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS duplicate_of_id INTEGER")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS related_ticket_ids JSONB")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS watchers JSONB")
            connection.exec_driver_sql("ALTER TABLE ticket_events ADD COLUMN IF NOT EXISTS visibility VARCHAR(16) DEFAULT 'internal'")


def get_db(): 
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
