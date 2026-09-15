from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from .job_queue import dispatch_jira_sync
from .llm import llm
from .models import Ticket, TicketEvent
from .rag import index
from .routing import route_ticket
from .safety import assess_input, validate_triage


class HelpdeskAgent:
    def run(self, db: Session, message: str, user_email: str, user_name: str, create_ticket: bool = True, user_role: str = "requester") -> dict:
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        safety = assess_input(message)
        trace = ["Received issue and normalized user context"]
        if safety.redaction_count:
            trace.append(f"Redacted {safety.redaction_count} sensitive value(s) before model processing")
        if safety.prompt_injection_detected:
            trace.append("Detected prompt-injection language; restricted automated actions")
        safe_message = safety.sanitized_text
        evidence = index.search(safe_message, db, user_role=user_role)
        trace.append("Retrieved relevant support documentation")
        raw_analysis = llm.classify(safe_message, evidence)
        analysis = validate_triage(raw_analysis, safety)
        trace.append("Validated model output against helpdesk safety policy")
        ticket_payload = None

        if create_ticket:
            ticket_number = f"HD-{uuid.uuid4().hex[:6].upper()}"
            route = route_ticket(analysis["category"], analysis["priority"])
            requires_approval = analysis["requires_approval"]
            ticket_status = "Needs review" if requires_approval else ("Escalated" if route["escalated"] else "Open")
            ticket = Ticket(
                ticket_number=ticket_number,
                title=analysis["intent"],
                description=f"Reported by {user_name} ({user_email})\n\n{safe_message}",
                requester_email=user_email,
                category=analysis["category"],
                priority=analysis["priority"],
                status=ticket_status,
                assignee=route["assignee"],
                source="AI Agent",
                evidence=evidence,
                sla_due_at=route["sla_due_at"],
                escalated_at=route["sla_due_at"] - timedelta(hours=2) if route["escalated"] and not requires_approval else None,
                escalation_reason=("Awaiting human approval due to safety policy" if requires_approval else route["escalation_reason"]),
                requires_approval=requires_approval,
                safety_flags=safety.flags,
            )
            db.add(ticket)
            db.commit()
            db.refresh(ticket)
            db.add(TicketEvent(ticket_id=ticket.id, event_type="created", actor="Relay AI", message=f"Ticket created and routed to {ticket.assignee}"))
            if ticket.status == "Escalated":
                db.add(TicketEvent(ticket_id=ticket.id, event_type="escalated", actor="Relay AI", message=ticket.escalation_reason or "High-priority ticket escalated"))
            if requires_approval:
                db.add(TicketEvent(ticket_id=ticket.id, event_type="safety", actor="Relay AI", message="Automation paused pending human approval", details={"flags": safety.flags}))
            db.commit()
            integration = dispatch_jira_sync(db, ticket)
            ticket_payload = {
                "id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "priority": ticket.priority,
                "assignee": ticket.assignee,
                "sla_due_at": ticket.sla_due_at.isoformat() if ticket.sla_due_at else None,
                "escalation_reason": ticket.escalation_reason,
                "external_provider": ticket.external_provider,
                "external_id": ticket.external_id,
                "external_url": ticket.external_url,
                "sync_error": ticket.sync_error,
                "integration_status": integration["status"],
                "requires_approval": ticket.requires_approval,
                "safety_flags": ticket.safety_flags or [],
                "created_at": ticket.created_at.isoformat(),
            }
            if requires_approval:
                trace.append(f"Created {ticket.ticket_number}; external actions paused pending approval")
            elif ticket.status == "Escalated":
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
            "safety_flags": safety.flags,
            "requires_approval": analysis["requires_approval"],
            "sanitized_input": safety.sanitized_text != message,
        }


agent = HelpdeskAgent()
