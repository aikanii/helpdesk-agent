from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
import uuid

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agent import agent
from .auth import create_access_token, get_current_user, hash_password, require_roles, verify_password
from .core import settings
from .integrations.jira import JiraError, jira
from .integrations.service import sync_ticket_to_jira
from .models import AgentFeedback, Conversation, ConversationMessage, SessionLocal, Ticket, TicketEvent, User, init_db
from .rag import ROLE_RANK, index
from .routing import route_ticket
from .schemas import (
    ChatRequest,
    ConversationCreate,
    ConversationMessageOut,
    ConversationOut,
    DiagnoseRequest,
    DiagnoseResponse,
    DocumentOut,
    EscalationRequest,
    EventCreate,
    FeedbackRequest,
    KnowledgeCreate,
    LoginRequest,
    TokenOut,
    TicketCreate,
    TicketEventOut,
    TicketOut,
    UserCreate,
    UserOut,
)


def seed_admin() -> None:
    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.email == settings.admin_email.lower()))
        if not existing:
            db.add(User(
                email=settings.admin_email.lower(),
                full_name=settings.admin_name,
                password_hash=hash_password(settings.admin_password),
                role="admin",
            ))
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    seed_admin()
    knowledge_db = SessionLocal()
    try:
        index.ensure_seeded(knowledge_db)
    finally:
        knowledge_db.close()
    seed_demo_data()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def seed_demo_data() -> None:
    db = SessionLocal()
    try:
        if db.scalar(select(func.count(Ticket.id))) == 0:
            now = datetime.now(timezone.utc)
            demo = [
                Ticket(ticket_number="HD-4F8A21", title="VPN connection failed", description="Unable to connect to the company VPN from home.", category="Access & Identity", priority="High", status="Open", assignee="Network Operations", source="AI Agent", evidence=index.search("VPN connection", db), created_at=now - timedelta(minutes=12)),
                Ticket(ticket_number="HD-7C2D10", title="Password reset request", description="User is locked out after several login attempts.", category="Access & Identity", priority="Medium", status="In progress", assignee="Identity Operations", source="Portal", evidence=index.search("password locked", db), created_at=now - timedelta(hours=2)),
                Ticket(ticket_number="HD-9AA013", title="Slack messages delayed", description="Messages are delayed for a small team.", category="Service Health", priority="Low", status="Open", assignee="Service Desk", source="AI Agent", evidence=index.search("Slack delayed", db), created_at=now - timedelta(hours=5)),
                Ticket(ticket_number="HD-2B7E04", title="Laptop running slowly", description="Laptop performance degraded since the latest update.", category="Endpoint", priority="Medium", status="Resolved", assignee="Endpoint Support", source="Portal", evidence=index.search("laptop slow", db), created_at=now - timedelta(days=1, hours=3)),
            ]
            for ticket in demo:
                route = route_ticket(ticket.category, ticket.priority)
                ticket.sla_due_at = route["sla_due_at"]
                if route["escalated"]:
                    ticket.status = "Escalated"
                    ticket.escalated_at = now - timedelta(minutes=10)
                    ticket.escalation_reason = route["escalation_reason"]
            db.add_all(demo)
            db.commit()
            for ticket in demo:
                record_event(db, ticket.id, "created", f"Seed ticket routed to {ticket.assignee}")
                if ticket.status == "Escalated":
                    record_event(db, ticket.id, "escalated", ticket.escalation_reason or "High-priority ticket escalated")
            db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def record_event(db: Session, ticket_id: int, event_type: str, message: str, actor: str = "Relay AI", details: dict | None = None) -> None:
    db.add(TicketEvent(ticket_id=ticket_id, event_type=event_type, actor=actor, message=message, details=details))


@app.get("/", include_in_schema=False)
def serve_app():
    return FileResponse(static_dir / "index.html")


@app.post("/api/auth/login", response_model=TokenOut)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == payload.username.strip().lower()))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password", headers={"WWW-Authenticate": "Bearer"})
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role},
    }


@app.get("/api/auth/me", response_model=UserOut)
def current_user_profile(current_user: User = Depends(get_current_user)):
    return current_user


@app.get("/api/auth/users", response_model=list[UserOut])
def list_users(current_admin: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.created_at.desc())).all()


@app.post("/api/auth/users", response_model=UserOut)
def create_user(payload: UserCreate, current_admin: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=409, detail="A user with that email already exists")
    user = User(email=email, full_name=payload.full_name.strip(), password_hash=hash_password(payload.password), role=payload.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.patch("/api/auth/users/{user_id}/active", response_model=UserOut)
def set_user_active(user_id: int, active: bool, current_admin: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_admin.id and not active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    user.is_active = active
    db.commit()
    db.refresh(user)
    return user


@app.get("/api/integrations/jira/status")
def jira_status(current_admin: User = Depends(require_roles("admin"))):
    return {
        "provider": "jira",
        "configured": jira.configured,
        "auto_sync": settings.jira_auto_sync,
        "base_url": settings.jira_base_url or None,
        "project_key": settings.jira_project_key or None,
    }


@app.post("/api/integrations/jira/test")
def test_jira_connection(current_admin: User = Depends(require_roles("admin"))):
    try:
        return {"status": "connected", "provider": "jira", "account": jira.test_connection()}
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/webhooks/jira")
def jira_webhook(payload: dict[str, Any], x_jira_webhook_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    if not settings.jira_webhook_secret or x_jira_webhook_token != settings.jira_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid Jira webhook token")
    issue = payload.get("issue", {})
    issue_key = issue.get("key")
    status_name = str(issue.get("fields", {}).get("status", {}).get("name", "")).lower()
    if not issue_key:
        raise HTTPException(status_code=400, detail="Webhook payload is missing issue.key")
    ticket = db.scalar(select(Ticket).where(Ticket.external_id == issue_key))
    if not ticket:
        return {"status": "ignored", "reason": "No linked Relay ticket", "external_id": issue_key}
    previous_status = ticket.status
    if status_name in {"done", "resolved", "closed", "complete", "completed"}:
        ticket.status = "Resolved"
    elif "progress" in status_name or status_name in {"in development", "in review"}:
        ticket.status = "In progress"
    else:
        ticket.status = "Open"
    ticket.last_synced_at = datetime.now(timezone.utc)
    ticket.sync_error = None
    if previous_status != ticket.status:
        record_event(db, ticket.id, "integration", f"Jira updated status to {ticket.status}", actor="Jira webhook", details={"external_id": issue_key})
    db.commit()
    return {"status": "updated", "ticket_number": ticket.ticket_number, "relay_status": ticket.status}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/api/stats")
def stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    tickets = db.scalars(select(Ticket)).all()
    open_tickets = [ticket for ticket in tickets if ticket.status != "Resolved"]
    urgent = [ticket for ticket in open_tickets if ticket.priority == "High"]
    return {
        "open": len(open_tickets),
        "urgent": len(urgent),
        "escalated": len([ticket for ticket in tickets if ticket.status == "Escalated"]),
        "resolved": len([ticket for ticket in tickets if ticket.status == "Resolved"]),
        "automation_rate": 84,
        "avg_response": "4m 18s",
    }


@app.post("/api/diagnose", response_model=DiagnoseResponse)
def diagnose(payload: DiagnoseRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return agent.run(db, payload.message, current_user.email, current_user.full_name, payload.create_ticket, current_user.role)


def conversation_payload(db: Session, conversation: Conversation) -> dict:
    messages = db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.created_at.asc())
    ).all()
    return {
        "id": conversation.id,
        "user_name": conversation.user_name,
        "user_email": conversation.user_email,
        "status": conversation.status,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "messages": messages,
    }


@app.post("/api/conversations", response_model=ConversationOut)
def create_conversation(payload: ConversationCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = Conversation(
        id=f"conv_{uuid.uuid4().hex[:12]}",
        user_name=current_user.full_name,
        user_email=current_user.email,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation_payload(db, conversation)


@app.get("/api/conversations", response_model=list[ConversationOut])
def list_conversations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Conversation).order_by(Conversation.updated_at.desc()).limit(50)
    if current_user.role == "requester":
        query = query.where(Conversation.user_email == current_user.email)
    conversations = db.scalars(query).all()
    return [conversation_payload(db, conversation) for conversation in conversations]


@app.get("/api/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if current_user.role == "requester" and conversation.user_email != current_user.email:
        raise HTTPException(status_code=403, detail="You do not have access to this conversation")
    return conversation_payload(db, conversation)


@app.post("/api/conversations/{conversation_id}/messages", response_model=DiagnoseResponse)
def send_conversation_message(conversation_id: str, payload: ChatRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if current_user.role == "requester" and conversation.user_email != current_user.email:
        raise HTTPException(status_code=403, detail="You do not have access to this conversation")
    user_message = ConversationMessage(conversation_id=conversation.id, role="user", content=payload.message)
    db.add(user_message)
    db.flush()
    result = agent.run(db, payload.message, current_user.email, current_user.full_name, payload.create_ticket, current_user.role)
    assistant_text = f"{result['summary']} Recommended next step: {result['actions'][0]['detail']}"
    db.add(ConversationMessage(conversation_id=conversation.id, role="assistant", content=assistant_text, payload=result))
    conversation.user_name = current_user.full_name
    conversation.user_email = current_user.email
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()
    return result


@app.post("/api/feedback")
def submit_feedback(payload: FeedbackRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    feedback = AgentFeedback(**payload.model_dump())
    db.add(feedback)
    db.commit()
    return {"status": "recorded", "feedback_id": feedback.id}


@app.get("/api/feedback/summary")
def feedback_summary(current_user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    rows = db.scalars(select(AgentFeedback)).all()
    helpful = len([row for row in rows if row.rating == "helpful"])
    return {"total": len(rows), "helpful": helpful, "not_helpful": len(rows) - helpful}


@app.get("/api/tickets/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.role == "requester" and ticket.requester_email != current_user.email:
        raise HTTPException(status_code=403, detail="You do not have access to this ticket")
    return ticket


@app.get("/api/tickets/{ticket_id}/events", response_model=list[TicketEventOut])
def list_ticket_events(ticket_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.role == "requester" and ticket.requester_email != current_user.email:
        raise HTTPException(status_code=403, detail="You do not have access to this ticket")
    return db.scalars(
        select(TicketEvent).where(TicketEvent.ticket_id == ticket_id).order_by(TicketEvent.created_at.asc())
    ).all()


@app.post("/api/tickets/{ticket_id}/events", response_model=TicketEventOut)
def add_ticket_event(ticket_id: int, payload: EventCreate, current_user: User = Depends(require_roles("agent", "manager", "admin")), db: Session = Depends(get_db)):
    if not db.get(Ticket, ticket_id):
        raise HTTPException(status_code=404, detail="Ticket not found")
    event = TicketEvent(ticket_id=ticket_id, event_type="note", actor=current_user.full_name, message=payload.message)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@app.get("/api/tickets", response_model=list[TicketOut])
def list_tickets(
    status: str | None = None,
    priority: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = select(Ticket).order_by(Ticket.created_at.desc())
    if status and status != "All":
        query = query.where(Ticket.status == status)
    if priority and priority != "All":
        query = query.where(Ticket.priority == priority)
    if q:
        query = query.where(Ticket.title.ilike(f"%{q}%"))
    if current_user.role == "requester":
        query = query.where(Ticket.requester_email == current_user.email)
    return db.scalars(query).all()


@app.post("/api/tickets", response_model=TicketOut)
def create_ticket(payload: TicketCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    number = f"HD-{datetime.now(timezone.utc).strftime('%m%d%H%M')}"
    route = route_ticket(payload.category, payload.priority)
    ticket = Ticket(
        ticket_number=number,
        requester_email=current_user.email,
        source="Portal",
        status="Escalated" if route["escalated"] else "Open",
        assignee=payload.assignee or route["assignee"],
        sla_due_at=route["sla_due_at"],
        escalated_at=datetime.now(timezone.utc) if route["escalated"] else None,
        escalation_reason=route["escalation_reason"],
        **payload.model_dump(exclude={"assignee"}),
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    record_event(db, ticket.id, "created", f"Ticket created and routed to {ticket.assignee}")
    if ticket.status == "Escalated":
        record_event(db, ticket.id, "escalated", ticket.escalation_reason or "High-priority ticket escalated")
    db.commit()
    sync_ticket_to_jira(db, ticket)
    return ticket


@app.post("/api/tickets/{ticket_id}/approve", response_model=TicketOut)
def approve_ticket(ticket_id: int, current_user: User = Depends(require_roles("manager", "admin")), db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.requires_approval = False
    ticket.approved_at = datetime.now(timezone.utc)
    ticket.approved_by = current_user.email
    if ticket.status == "Needs review":
        ticket.status = "Escalated" if ticket.priority == "High" else "Open"
    record_event(db, ticket.id, "approval", "Safety review approved by manager", actor=current_user.full_name)
    db.commit()
    if jira.configured:
        try:
            sync_ticket_to_jira(db, ticket, force=True)
        except JiraError as exc:
            ticket.sync_error = str(exc)
            db.commit()
    db.refresh(ticket)
    return ticket


@app.post("/api/tickets/{ticket_id}/sync", response_model=TicketOut)
def sync_ticket(ticket_id: int, current_user: User = Depends(require_roles("agent", "manager", "admin")), db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    try:
        sync_ticket_to_jira(db, ticket, force=True)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.refresh(ticket)
    return ticket


@app.post("/api/tickets/{ticket_id}/escalate", response_model=TicketOut)
def escalate_ticket(ticket_id: int, payload: EscalationRequest, current_user: User = Depends(require_roles("agent", "manager", "admin")), db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.requires_approval and not ticket.approved_by:
        raise HTTPException(status_code=409, detail="This ticket requires manager approval before escalation")
    route = route_ticket(ticket.category, "High", force_escalation=True)
    ticket.priority = "High"
    ticket.status = "Escalated"
    ticket.assignee = route["assignee"]
    ticket.sla_due_at = route["sla_due_at"]
    ticket.escalated_at = datetime.now(timezone.utc)
    ticket.escalation_reason = payload.reason or "Escalated manually by an agent"
    db.commit()
    db.refresh(ticket)
    record_event(db, ticket.id, "escalated", ticket.escalation_reason, actor=current_user.full_name)
    db.commit()
    sync_ticket_to_jira(db, ticket, comment=ticket.escalation_reason)
    return ticket


@app.patch("/api/tickets/{ticket_id}/status", response_model=TicketOut)
def update_ticket_status(ticket_id: int, status: str, current_user: User = Depends(require_roles("agent", "manager", "admin")), db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if status not in {"Open", "In progress", "Escalated", "Needs review", "Resolved"}:
        raise HTTPException(status_code=400, detail="Unsupported status")
    if ticket.requires_approval and not ticket.approved_by and status != "Needs review":
        raise HTTPException(status_code=409, detail="This ticket requires manager approval before status changes")
    previous_status = ticket.status
    ticket.status = status
    db.commit()
    db.refresh(ticket)
    if previous_status != status:
        status_message = f"Status changed from {previous_status} to {status}"
        record_event(db, ticket.id, "status_changed", status_message, actor=current_user.full_name)
        db.commit()
        sync_ticket_to_jira(db, ticket, comment=status_message)
    return ticket


@app.get("/api/docs", response_model=list[DocumentOut])
def list_docs(q: str | None = Query(default=None, max_length=100), category: str | None = Query(default=None, max_length=64), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return index.search(q, db, limit=10, user_role=current_user.role, category=category) if q else index.all(db, user_role=current_user.role, category=category)


@app.post("/api/docs", response_model=DocumentOut)
def add_doc(payload: KnowledgeCreate, current_user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    return index.ingest(db, payload.title, payload.content, payload.category, payload.source, payload.source_url, payload.min_role, current_user.email)


def extract_uploaded_text(filename: str, payload: bytes) -> str:
    extension = Path(filename).suffix.lower()
    if extension in {".txt", ".md", ".csv", ".json", ".html"}:
        return payload.decode("utf-8", errors="replace")
    if extension == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(payload))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    if extension == ".docx":
        from docx import Document as DocxDocument
        document = DocxDocument(BytesIO(payload))
        return "\n\n".join(paragraph.text for paragraph in document.paragraphs)
    raise HTTPException(status_code=415, detail="Supported files: PDF, DOCX, TXT, Markdown, CSV, JSON, and HTML")


@app.post("/api/docs/upload", response_model=DocumentOut)
async def upload_doc(
    file: UploadFile = File(...),
    category: str = "General",
    min_role: str = "requester",
    current_user: User = Depends(require_roles("admin", "manager")),
    db: Session = Depends(get_db),
):
    payload = await file.read()
    if len(payload) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Knowledge files must be 10 MB or smaller")
    content = extract_uploaded_text(file.filename or "upload.txt", payload).strip()
    if len(content) < 20:
        raise HTTPException(status_code=422, detail="The uploaded file did not contain enough text to index")
    return index.ingest(db, Path(file.filename or "upload.txt").stem, content, category, file.filename or "Uploaded document", None, min_role, current_user.email)


@app.delete("/api/docs/{doc_id}")
def delete_doc(doc_id: str, current_user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    if not index.delete(db, doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted", "document_id": doc_id}


@app.get("/api/docs/{doc_id}", response_model=DocumentOut)
def get_doc(doc_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    match = index.get(db, doc_id)
    if not match:
        raise HTTPException(status_code=404, detail="Document not found")
    if ROLE_RANK.get(current_user.role, 0) < ROLE_RANK.get(match["min_role"], 0):
        raise HTTPException(status_code=403, detail="You do not have access to this document")
    return match
