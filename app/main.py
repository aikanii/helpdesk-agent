from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agent import agent
from .core import settings
from .models import SessionLocal, Ticket, init_db
from .rag import index
from .routing import route_ticket
from .schemas import DiagnoseRequest, DiagnoseResponse, DocumentOut, EscalationRequest, TicketCreate, TicketOut


app = FastAPI(title=settings.app_name, version="0.1.0")
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
    finally:
        db.close()


@app.on_event("startup")
def startup() -> None:
    init_db()
    seed_demo_data()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
    return ticket


@app.patch("/api/tickets/{ticket_id}/status", response_model=TicketOut)
def update_ticket_status(ticket_id: int, status: str, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if status not in {"Open", "In progress", "Escalated", "Resolved"}:
        raise HTTPException(status_code=400, detail="Unsupported status")
    ticket.status = status
    db.commit()
    db.refresh(ticket)
    return ticket


@app.get("/api/docs", response_model=list[DocumentOut])
def list_docs(q: str | None = Query(default=None, max_length=100)):
    return index.search(q, limit=10) if q else index.all()


@app.get("/api/docs/{doc_id}")
def get_doc(doc_id: str):
    match = next((doc for doc in index.all() if doc["id"] == doc_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Document not found")
    return match
