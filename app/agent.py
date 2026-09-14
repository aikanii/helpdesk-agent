from __future__ import annotations

import uuid
from sqlalchemy.orm import Session

from .llm import llm
from .models import Ticket
from .rag import index


class HelpdeskAgent:
    def run(self, db: Session, message: str, user_email: str, user_name: str, create_ticket: bool = True) -> dict:
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        trace = ["Received issue and normalized user context", "Retrieved relevant support documentation", "Classified intent and estimated impact"]
        evidence = index.search(message)
        analysis = llm.classify(message, evidence)
        ticket_payload = None

        if create_ticket:
            ticket_number = f"HD-{uuid.uuid4().hex[:6].upper()}"
            ticket = Ticket(
                ticket_number=ticket_number,
                title=analysis["intent"],
                description=f"Reported by {user_name} ({user_email})\n\n{message}",
                category=analysis["category"],
                priority=analysis["priority"],
                status="Open",
                assignee="Service Desk",
                source="AI Agent",
                evidence=evidence,
            )
            db.add(ticket)
            db.commit()
            db.refresh(ticket)
            ticket_payload = {
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "priority": ticket.priority,
                "assignee": ticket.assignee,
                "created_at": ticket.created_at.isoformat(),
            }
            trace.append(f"Created and routed ticket {ticket.ticket_number}")
        else:
            trace.append("Ticket creation skipped by user")

        return {
            "run_id": run_id,
            "intent": analysis["intent"],
            "confidence": analysis["confidence"],
            "summary": analysis["summary"],
            "category": analysis["category"],
            "priority": analysis["priority"],
            "actions": analysis["actions"],
            "evidence": evidence,
            "ticket": ticket_payload,
            "agent_trace": trace,
        }


agent = HelpdeskAgent()
