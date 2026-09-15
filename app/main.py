from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agent import agent
from .core import settings
from .models import AgentFeedback, Conversation, ConversationMessage, SessionLocal, Ticket, TicketEvent, init_db
from .rag import index
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
    TicketCreate,
    TicketEventOut,
    TicketOut,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
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
                Ticket(ticket_number="HD-4F8A21", title="VPN connection failed", description="Unable to connect to the company VPN from home.", category="Access & Identity", priority="High", status="Open", assignee="Network Operations", source="AI Agent", evidence=index.search("VPN connection"), created_at=now - timedelta(minutes=12)),
                Ticket(ticket_number="HD-7C2D10", title="Password reset request", description="User is locked out after several login attempts.", category="Access & Identity", priority="Medium", status="In progress", assignee="Identity Operations", source="Portal", evidence=index.search("password locked"), created_at=now - timedelta(hours=2)),
                Ticket(ticket_number="HD-9AA013", title="Slack messages delayed", description="Messages are delayed for a small team.", category="Service Health", priority="Low", status="Open", assignee="Service Desk", source="AI Agent", evidence=index.search("Slack delayed"), created_at=now - timedelta(hours=5)),
                Ticket(ticket_number="HD-2B7E04", title="Laptop running slowly", description="Laptop performance degraded since the latest update.", category="Endpoint", priority="Medium", status="Resolved", assignee="Endpoint Support", source="Portal", evidence=index.search("laptop slow"), created_at=now - timedelta(days=1, hours=3)),
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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/api/stats")
def stats(db: Session = Depends(get_db)) -> dict[str, Any]:
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
def diagnose(payload: DiagnoseRequest, db: Session = Depends(get_db)):
    return agent.run(db, payload.message, payload.user_email, payload.user_name, payload.create_ticket)


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
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db)):
    conversation = Conversation(
        id=f"conv_{uuid.uuid4().hex[:12]}",
        user_name=payload.user_name,
        user_email=payload.user_email,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation_payload(db, conversation)


@app.get("/api/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    conversations = db.scalars(select(Conversation).order_by(Conversation.updated_at.desc()).limit(50)).all()
    return [conversation_payload(db, conversation) for conversation in conversations]


@app.get("/api/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: str, db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation_payload(db, conversation)


@app.post("/api/conversations/{conversation_id}/messages", response_model=DiagnoseResponse)
def send_conversation_message(conversation_id: str, payload: ChatRequest, db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    user_message = ConversationMessage(conversation_id=conversation.id, role="user", content=payload.message)
    db.add(user_message)
    db.flush()
    result = agent.run(db, payload.message, payload.user_email, payload.user_name, payload.create_ticket)
    assistant_text = f"{result['summary']} Recommended next step: {result['actions'][0]['detail']}"
    db.add(ConversationMessage(conversation_id=conversation.id, role="assistant", content=assistant_text, payload=result))
    conversation.user_name = payload.user_name
    conversation.user_email = payload.user_email
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()
    return result


@app.post("/api/feedback")
def submit_feedback(payload: FeedbackRequest, db: Session = Depends(get_db)):
    feedback = AgentFeedback(**payload.model_dump())
    db.add(feedback)
    db.commit()
    return {"status": "recorded", "feedback_id": feedback.id}


@app.get("/api/feedback/summary")
def feedback_summary(db: Session = Depends(get_db)):
    rows = db.scalars(select(AgentFeedback)).all()
    helpful = len([row for row in rows if row.rating == "helpful"])
    return {"total": len(rows), "helpful": helpful, "not_helpful": len(rows) - helpful}


@app.get("/api/tickets/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: int, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.get("/api/tickets/{ticket_id}/events", response_model=list[TicketEventOut])
def list_ticket_events(ticket_id: int, db: Session = Depends(get_db)):
    if not db.get(Ticket, ticket_id):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return db.scalars(
        select(TicketEvent).where(TicketEvent.ticket_id == ticket_id).order_by(TicketEvent.created_at.asc())
    ).all()


@app.post("/api/tickets/{ticket_id}/events", response_model=TicketEventOut)
def add_ticket_event(ticket_id: int, payload: EventCreate, db: Session = Depends(get_db)):
    if not db.get(Ticket, ticket_id):
        raise HTTPException(status_code=404, detail="Ticket not found")
    event = TicketEvent(ticket_id=ticket_id, event_type="note", actor=payload.actor, message=payload.message)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@app.get("/api/tickets", response_model=list[TicketOut])
def list_tickets(
    status: str | None = None,
    priority: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
):
    query = select(Ticket).order_by(Ticket.created_at.desc())
    if status and status != "All":
        query = query.where(Ticket.status == status)
    if priority and priority != "All":
        query = query.where(Ticket.priority == priority)
    if q:
        query = query.where(Ticket.title.ilike(f"%{q}%"))
    return db.scalars(query).all()


@app.post("/api/tickets", response_model=TicketOut)
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db)):
    number = f"HD-{datetime.now(timezone.utc).strftime('%m%d%H%M')}"
    route = route_ticket(payload.category, payload.priority)
    ticket = Ticket(
        ticket_number=number,
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
    return ticket


@app.post("/api/tickets/{ticket_id}/escalate", response_model=TicketOut)
def escalate_ticket(ticket_id: int, payload: EscalationRequest, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    route = route_ticket(ticket.category, "High", force_escalation=True)
    ticket.priority = "High"
    ticket.status = "Escalated"
    ticket.assignee = route["assignee"]
    ticket.sla_due_at = route["sla_due_at"]
    ticket.escalated_at = datetime.now(timezone.utc)
    ticket.escalation_reason = payload.reason or "Escalated manually by an agent"
    db.commit()
    db.refresh(ticket)
    record_event(db, ticket.id, "escalated", ticket.escalation_reason, actor="Helpdesk agent")
    db.commit()
    return ticket


@app.patch("/api/tickets/{ticket_id}/status", response_model=TicketOut)
def update_ticket_status(ticket_id: int, status: str, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if status not in {"Open", "In progress", "Escalated", "Resolved"}:
        raise HTTPException(status_code=400, detail="Unsupported status")
    previous_status = ticket.status
    ticket.status = status
    db.commit()
    db.refresh(ticket)
    if previous_status != status:
        record_event(db, ticket.id, "status_changed", f"Status changed from {previous_status} to {status}", actor="Helpdesk agent")
        db.commit()
    return ticket


@app.get("/api/docs", response_model=list[DocumentOut])
def list_docs(q: str | None = Query(default=None, max_length=100)):
    return index.search(q, limit=10) if q else index.all()


@app.post("/api/docs", response_model=DocumentOut)
def add_doc(payload: KnowledgeCreate):
    return index.add(payload.title, payload.content, payload.category, payload.source)


@app.delete("/api/docs/{doc_id}")
def delete_doc(doc_id: str):
    if not index.delete(doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted", "document_id": doc_id}


@app.get("/api/docs/{doc_id}")
def get_doc(doc_id: str):
    match = next((doc for doc in index.all() if doc["id"] == doc_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Document not found")
    return match
