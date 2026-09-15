from __future__ import annotations

import uuid
from datetime import timedelta
from sqlalchemy.orm import Session

from .llm import llm
from .models import Ticket, TicketEvent
from .rag import index
from .routing import route_ticket


class HelpdeskAgent:
    def run(self, db: Session, message: str, user_email: str, user_name: str, create_ticket: bool = True) -> dict:
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        trace = ["Received issue and normalized user context", "Retrieved relevant support documentation", "Classified intent and estimated impact"]
        evidence = index.search(message)
        analysis = llm.classify(message, evidence)
        ticket_payload = None

        if create_ticket:
            ticket_number = f"HD-{uuid.uuid4().hex[:6].upper()}"
            route = route_ticket(analysis["category"], analysis["priority"])
            ticket = Ticket(
                ticket_number=ticket_number,
                title=analysis["intent"],
                description=f"Reported by {user_name} ({user_email})\n\n{message}",
                category=analysis["category"],
                priority=analysis["priority"],
                status="Escalated" if route["escalated"] else "Open",
                assignee=route["assignee"],
                source="AI Agent",
                evidence=evidence,
                sla_due_at=route["sla_due_at"],
                escalated_at=route["sla_due_at"] - timedelta(hours=2) if route["escalated"] else None,
                escalation_reason=route["escalation_reason"],
            )
            db.add(ticket)
            db.commit()
            db.refresh(ticket)
            db.add(TicketEvent(ticket_id=ticket.id, event_type="created", actor="Relay AI", message=f"Ticket created and routed to {ticket.assignee}"))
            if ticket.status == "Escalated":
                db.add(TicketEvent(ticket_id=ticket.id, event_type="escalated", actor="Relay AI", message=ticket.escalation_reason or "High-priority ticket escalated"))
            db.commit()
            ticket_payload = {
                "id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "priority": ticket.priority,
                "assignee": ticket.assignee,
                "sla_due_at": ticket.sla_due_at.isoformat() if ticket.sla_due_at else None,
                "escalation_reason": ticket.escalation_reason,
                "created_at": ticket.created_at.isoformat(),
            }
            if ticket.status == "Escalated":
                trace.append(f"Escalated {ticket.ticket_number} to {ticket.assignee} with a 2-hour SLA")
            else:
                trace.append(f"Created and routed ticket {ticket.ticket_number} to {ticket.assignee}")
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
