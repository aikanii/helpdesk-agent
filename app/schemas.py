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
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: str
    title: str
    content: str
    category: str
    updated: str
