from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..core import settings
from ..models import Ticket, TicketEvent
from .jira import JiraError, jira


def sync_ticket_to_jira(db: Session, ticket: Ticket, force: bool = False, comment: str | None = None) -> dict[str, Any]:
    if not jira.configured:
        if force:
            raise JiraError("Jira integration is not configured")
        return {"status": "not_configured", "provider": "jira"}
    if not force and not settings.jira_auto_sync and not ticket.external_id:
        return {"status": "disabled", "provider": "jira"}
    try:
        if not ticket.external_id:
            issue = jira.create_issue(ticket)
            ticket.external_provider = jira.provider
            ticket.external_id = issue["id"]
            ticket.external_url = issue["url"]
            db.add(TicketEvent(ticket_id=ticket.id, event_type="integration", actor="Relay AI", message=f"Created Jira issue {issue['id']}", details={"provider": "jira", "external_id": issue["id"]}))
        jira.sync_status(ticket.external_id, ticket.status)
        if comment:
            jira.add_comment(ticket.external_id, comment)
        ticket.last_synced_at = datetime.now(timezone.utc)
        ticket.sync_error = None
        db.commit()
        return {"status": "synced", "provider": "jira", "external_id": ticket.external_id, "external_url": ticket.external_url}
    except JiraError as exc:
        ticket.sync_error = str(exc)
        db.commit()
        if force:
            raise
        return {"status": "error", "provider": "jira", "error": str(exc)}
