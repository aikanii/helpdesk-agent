from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=180)
    password: str = Field(min_length=8, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict[str, Any]


class JobOut(BaseModel):
    id: str
    job_type: str
    status: str
    payload: dict[str, Any]
    result: dict[str, Any] | None
    idempotency_key: str | None
    attempts: int
    max_attempts: int
    run_after: datetime
    locked_at: datetime | None
    locked_by: str | None
    last_error: str | None
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: str = Field(min_length=5, max_length=180)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    role: str = Field(default="requester", pattern="^(requester|agent|manager|admin)$")


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=180)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=8, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class NotificationOut(BaseModel):
    id: str
    notification_type: str
    title: str
    message: str
    link: str | None
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationPreferenceOut(BaseModel):
    user_id: int
    in_app_enabled: bool
    email_enabled: bool
    email_on_assignment: bool
    email_on_status_change: bool
    email_on_sla_breach: bool

    model_config = {"from_attributes": True}


class NotificationPreferenceUpdate(BaseModel):
    in_app_enabled: bool = True
    email_enabled: bool = True
    email_on_assignment: bool = True
    email_on_status_change: bool = True
    email_on_sla_breach: bool = True


class RoutingRuleOut(BaseModel):
    id: int
    category: str
    team: str
    sla_hours: int
    auto_escalate_high: bool
    updated_by: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoutingRuleUpdate(BaseModel):
    category: str = Field(min_length=2, max_length=64)
    team: str = Field(min_length=2, max_length=120)
    sla_hours: int = Field(ge=1, le=168)
    auto_escalate_high: bool = True


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
    visibility: str = Field(default="internal", pattern="^(internal|public)$")


class TicketStatusUpdate(BaseModel):
    status: str
    resolution_code: str | None = Field(default=None, max_length=64)


class LinkRequest(BaseModel):
    relation: str = Field(pattern="^(parent|duplicate|related)$")
    target_ticket_id: int


class WatcherRequest(BaseModel):
    email: str = Field(min_length=5, max_length=180)
    action: str = Field(default="add", pattern="^(add|remove)$")


class KnowledgeCreate(BaseModel):
    title: str = Field(min_length=3, max_length=220)
    content: str = Field(min_length=20, max_length=20000)
    category: str = Field(default="General", max_length=64)
    source: str = Field(default="Uploaded runbook", max_length=120)
    source_url: str | None = Field(default=None, max_length=500)
    min_role: str = Field(default="requester", pattern="^(requester|agent|manager|admin)$")


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
    safety_flags: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    sanitized_input: bool = False


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
    requester_email: str | None
    category: str
    priority: str
    status: str
    assignee: str | None
    source: str
    evidence: list[dict[str, Any]]
    sla_due_at: datetime | None
    escalated_at: datetime | None
    escalation_reason: str | None
    external_provider: str | None
    external_id: str | None
    external_url: str | None
    last_synced_at: datetime | None
    sync_error: str | None
    requires_approval: bool
    safety_flags: list[str] | None
    approved_at: datetime | None
    approved_by: str | None
    resolution_code: str | None
    resolved_at: datetime | None
    closed_at: datetime | None
    reopened_at: datetime | None
    parent_ticket_id: int | None
    duplicate_of_id: int | None
    related_ticket_ids: list[int] | None
    watchers: list[str] | None
    created_at: datetime

    @computed_field
    @property
    def sla_state(self) -> str:
        if self.status in {"Resolved", "Closed"}:
            return "complete"
        if not self.sla_due_at:
            return "not_set"
        due = self.sla_due_at
        if due.tzinfo is None:
            from datetime import timezone
            due = due.replace(tzinfo=timezone.utc)
        seconds_left = (due - datetime.now(timezone.utc)).total_seconds()
        if seconds_left <= 0:
            return "breached"
        if seconds_left <= 3600:
            return "at_risk"
        return "on_track"

    model_config = {"from_attributes": True}


class TicketAttachmentOut(BaseModel):
    id: int
    ticket_id: int
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: str
    title: str
    content: str
    category: str
    updated: str
    source: str = "Seed runbook"
    source_url: str | None = None
    min_role: str = "requester"
    status: str = "indexed"
    chunk_count: int = 0


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
    visibility: str
    created_at: datetime

    model_config = {"from_attributes": True}
