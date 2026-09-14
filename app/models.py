from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, Integer, JSON, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .core import settings


class Base(DeclarativeBase):
    pass


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), default="General")
    priority: Mapped[str] = mapped_column(String(24), default="Medium")
    status: Mapped[str] = mapped_column(String(24), default="Open")
    assignee: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="AI Agent")
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    sla_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    escalation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # Keep the demo self-healing when an existing local SQLite database predates
    # the escalation fields. Production deployments should use Alembic migrations.
    with engine.begin() as connection:
        if settings.database_url.startswith("sqlite"):
            existing = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(tickets)").fetchall()}
            columns = {
                "sla_due_at": "DATETIME",
                "escalated_at": "DATETIME",
                "escalation_reason": "TEXT",
            }
            for name, column_type in columns.items():
                if name not in existing:
                    connection.exec_driver_sql(f"ALTER TABLE tickets ADD COLUMN {name} {column_type}")
        else:
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS sla_due_at TIMESTAMP WITH TIME ZONE")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMP WITH TIME ZONE")
            connection.exec_driver_sql("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS escalation_reason TEXT")


def get_db(): 
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
