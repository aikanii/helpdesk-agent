from __future__ import annotations

from datetime import datetime, timezone


STATUSES = {"Open", "In progress", "Pending", "Escalated", "Needs review", "Resolved", "Closed", "Reopened"}
RESOLUTION_CODES = {"Fixed", "Workaround", "User education", "Duplicate", "Not reproducible", "No action"}

TRANSITIONS = {
    "Open": {"In progress", "Pending", "Escalated", "Needs review", "Resolved"},
    "In progress": {"Pending", "Escalated", "Resolved"},
    "Pending": {"In progress", "Resolved", "Closed"},
    "Escalated": {"In progress", "Pending", "Resolved"},
    "Needs review": {"Open", "In progress", "Escalated"},
    "Resolved": {"Closed", "Reopened", "In progress"},
    "Closed": {"Reopened"},
    "Reopened": {"In progress", "Pending", "Escalated", "Resolved"},
}


def validate_transition(current: str, target: str) -> None:
    if target not in STATUSES:
        raise ValueError(f"Unsupported ticket status: {target}")
    if current == target:
        return
    if target not in TRANSITIONS.get(current, set()):
        raise ValueError(f"Ticket cannot transition from {current} to {target}")


def sla_state(status: str, due_at: datetime | None) -> str:
    if status in {"Resolved", "Closed"}:
        return "complete"
    if not due_at:
        return "not_set"
    due = due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)
    seconds_left = (due - datetime.now(timezone.utc)).total_seconds()
    if seconds_left <= 0:
        return "breached"
    if seconds_left <= 3600:
        return "at_risk"
    return "on_track"
