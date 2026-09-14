from __future__ import annotations

from datetime import datetime, timedelta, timezone


TEAM_BY_CATEGORY = {
    "Access & Identity": "Identity Operations",
    "Service Health": "Service Operations",
    "Endpoint": "Endpoint Support",
    "Messaging": "Messaging Operations",
    "General": "Service Desk",
}

SLA_HOURS_BY_PRIORITY = {
    "High": 4,
    "Medium": 8,
    "Low": 24,
}


def route_ticket(category: str, priority: str, force_escalation: bool = False) -> dict:
    """Return the owning team, SLA deadline, and escalation state for a ticket."""
    now = datetime.now(timezone.utc)
    is_escalated = force_escalation or priority == "High"
    # High-impact incidents get a tighter SLA when they are escalated.
    hours = 2 if is_escalated else SLA_HOURS_BY_PRIORITY.get(priority, 24)
    return {
        "assignee": TEAM_BY_CATEGORY.get(category, TEAM_BY_CATEGORY["General"]),
        "sla_due_at": now + timedelta(hours=hours),
        "escalated": is_escalated,
        "escalation_reason": "High-priority issue automatically routed by Relay" if is_escalated else None,
    }
