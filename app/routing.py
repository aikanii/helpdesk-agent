from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import RoutingRule

DEFAULT_RULES: dict[str, dict[str, Any]] = {
    "Access & Identity": {"team": "Identity Operations", "sla_hours": 8, "auto_escalate_high": True},
    "Service Health": {"team": "Service Operations", "sla_hours": 4, "auto_escalate_high": True},
    "Endpoint": {"team": "Endpoint Support", "sla_hours": 24, "auto_escalate_high": True},
    "Messaging": {"team": "Messaging Operations", "sla_hours": 8, "auto_escalate_high": True},
    "General": {"team": "Service Desk", "sla_hours": 24, "auto_escalate_high": True},
}


def seed_routing_rules(db: Session) -> None:
    if db.scalar(select(RoutingRule.id).limit(1)):
        return
    for category, rule in DEFAULT_RULES.items():
        db.add(RoutingRule(category=category, **rule))
    db.commit()


def routing_rules(db: Session) -> dict[str, dict[str, Any]]:
    rows = db.scalars(select(RoutingRule)).all()
    return {row.category: {"team": row.team, "sla_hours": row.sla_hours, "auto_escalate_high": row.auto_escalate_high} for row in rows}


def route_ticket(category: str, priority: str, force_escalation: bool = False, rules: dict[str, dict[str, Any]] | None = None) -> dict:
    active_rules = rules or DEFAULT_RULES
    rule = active_rules.get(category, active_rules.get("General", DEFAULT_RULES["General"]))
    is_escalated = force_escalation or (priority == "High" and rule.get("auto_escalate_high", True))
    hours = 2 if is_escalated else int(rule.get("sla_hours", 24))
    now = datetime.now(timezone.utc)
    return {
        "assignee": rule["team"],
        "sla_due_at": now + timedelta(hours=hours),
        "escalated": is_escalated,
        "escalation_reason": "High-priority issue automatically routed by Relay" if is_escalated else None,
    }
