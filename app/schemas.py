from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DiagnoseRequest(BaseModel):
    message: str = Field(min_length=3, max_length=5000)
    user_email: str = "alex.morgan@acme.co"
    user_name: str = "Alex Morgan"
    create_ticket: bool = True


class Evidence(BaseModel):
    id: str
    title: str
    excerpt: str
    score: float
    type: str = "Runbook"


class ChatRequest(BaseModel):
    message: str = Field(min_length=3, max_length=5000)
    user_email: str = "alex.morgan@acme.co"
    user_name: str = "Alex Morgan"
    create_ticket: bool = True


class FeedbackRequest(BaseModel):
    run_id: str = Field(min_length=3, max_length=40)
    ticket_number: str | None = None
    rating: str = Field(pattern="^(helpful|not_helpful)$")
    comment: str | None = Field(default=None, max_length=1000)


class EventCreate(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    actor: str = "Alex Morgan"


class KnowledgeCreate(BaseModel):
    title: str = Field(min_length=3, max_length=220)
    content: str = Field(min_length=20, max_length=20000)
    category: str = Field(default="General", max_length=64)
    source: str = Field(default="Uploaded runbook", max_length=120)


class Action(BaseModel):
    label: str
    detail: str
    status: str = "recommended"


class DiagnoseResponse(BaseModel):
    run_id: str
    intent: str
    confidence: int
    summary: str
    category: str
    priority: str
    actions: list[Action]
    evidence: list[Evidence]
    ticket: dict[str, Any] | None = None
    agent_trace: list[str]


class TicketCreate(BaseModel):
    title: str
    description: str
    category: str = "General"
    priority: str = "Medium"
    assignee: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class EscalationRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class TicketOut(BaseModel):
    id: int
    ticket_number: str
    title: str
    description: str
    category: str
    priority: str
    status: str
    assignee: str | None
    source: str
    evidence: list[dict[str, Any]]
    sla_due_at: datetime | None
    escalated_at: datetime | None
    escalation_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: str
    title: str
    content: str
    category: str
    updated: str
    source: str = "Seed runbook"


class ConversationCreate(BaseModel):
    user_name: str = "Alex Morgan"
    user_email: str = "alex.morgan@acme.co"


class ConversationMessageOut(BaseModel):
    id: int
    role: str
    content: str
    payload: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: str
    user_name: str
    user_email: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessageOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TicketEventOut(BaseModel):
    id: int
    ticket_id: int
    event_type: str
    actor: str
    message: str
    details: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}
