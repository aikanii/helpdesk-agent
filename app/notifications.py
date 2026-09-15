from __future__ import annotations

import smtplib
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .core import settings
from .models import Notification, NotificationPreference, Ticket, User


def get_preferences(db: Session, user_id: int) -> NotificationPreference:
    preferences = db.get(NotificationPreference, user_id)
    if not preferences:
        preferences = NotificationPreference(user_id=user_id)
        db.add(preferences)
        db.commit()
        db.refresh(preferences)
    return preferences


def create_notification(
    db: Session,
    user: User,
    notification_type: str,
    title: str,
    body: str,
    ticket_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    channel: str = "in_app",
) -> Notification | None:
    preferences = get_preferences(db, user.id)
    if channel == "in_app" and not preferences.in_app_enabled:
        return None
    if channel == "email" and (not preferences.email_enabled or not settings.smtp_host):
        return None
    if idempotency_key:
        existing = db.scalar(select(Notification).where(Notification.idempotency_key == idempotency_key))
        if existing:
            return existing
    notification = Notification(
        id=f"notif_{uuid.uuid4().hex[:14]}",
        user_id=user.id,
        ticket_id=ticket_id,
        notification_type=notification_type,
        title=title,
        body=body,
        channel=channel,
        status="queued",
        notification_metadata=metadata,
        idempotency_key=idempotency_key,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    from .job_queue import queue
    queue.enqueue(db, "send_notification", {"notification_id": notification.id}, idempotency_key=f"deliver:{notification.id}")
    return notification


def notify_user_ids(
    db: Session,
    user_ids: list[int],
    notification_type: str,
    title: str,
    body: str,
    ticket_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    dedupe_suffix: str = "",
) -> list[str]:
    created: list[str] = []
    for user_id in sorted(set(user_ids)):
        user = db.get(User, user_id)
        if not user or not user.is_active:
            continue
        base_key = f"{notification_type}:{user.id}:{ticket_id or 'none'}:{dedupe_suffix}"
        in_app = create_notification(db, user, notification_type, title, body, ticket_id, metadata, base_key, "in_app")
        if in_app:
            created.append(in_app.id)
        preferences = get_preferences(db, user.id)
        if preferences.email_enabled and settings.smtp_host:
            email_notification = create_notification(db, user, notification_type, title, body, ticket_id, metadata, f"{base_key}:email", "email")
            if email_notification:
                created.append(email_notification.id)
    return created


def notify_ticket(db: Session, ticket: Ticket, notification_type: str, title: str, body: str, dedupe_suffix: str = "") -> list[str]:
    emails = set([ticket.requester_email] if ticket.requester_email else [])
    emails.update(ticket.watchers or [])
    if not emails:
        return []
    users = db.scalars(select(User).where(User.email.in_(emails), User.is_active.is_(True))).all()
    return notify_user_ids(db, [user.id for user in users], notification_type, title, body, ticket.id, {"ticket_number": ticket.ticket_number}, dedupe_suffix)


def deliver_notification(db: Session, notification: Notification) -> dict[str, Any]:
    user = db.get(User, notification.user_id)
    if not user:
        notification.status = "skipped"
        notification.error = "User no longer exists"
        db.commit()
        return {"status": "skipped", "reason": notification.error}
    if notification.channel == "in_app":
        notification.status = "sent"
        notification.sent_at = datetime.now(timezone.utc)
        notification.error = None
        db.commit()
        return {"status": "sent", "channel": "in_app"}
    if notification.channel == "email":
        if not settings.smtp_host:
            notification.status = "skipped"
            notification.error = "SMTP is not configured"
            db.commit()
            return {"status": "skipped", "reason": notification.error}
        message = EmailMessage()
        message["Subject"] = notification.title
        message["From"] = settings.smtp_from
        message["To"] = user.email
        message.set_content(notification.body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            if settings.smtp_tls:
                server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
        notification.status = "sent"
        notification.sent_at = datetime.now(timezone.utc)
        notification.error = None
        db.commit()
        return {"status": "sent", "channel": "email"}
    raise RuntimeError(f"Unsupported notification channel: {notification.channel}")
