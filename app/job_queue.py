from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .core import settings
from .integrations.service import sync_ticket_to_jira
from .models import Job, SessionLocal, Ticket, TicketEvent

logger = logging.getLogger("relay.jobs")


class JobQueue:
    def enqueue(
        self,
        db: Session,
        job_type: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        max_attempts: int = 5,
        delay_seconds: int = 0,
    ) -> Job:
        if idempotency_key:
            existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
            if existing:
                return existing
        job = Job(
            id=f"job_{uuid.uuid4().hex[:14]}",
            job_type=job_type,
            status="queued",
            payload=payload,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            run_after=datetime.now(timezone.utc) + timedelta(seconds=delay_seconds),
        )
        db.add(job)
        try:
            db.commit()
            db.refresh(job)
            return job
        except IntegrityError:
            db.rollback()
            if idempotency_key:
                existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
                if existing:
                    return existing
            raise

    def stats(self, db: Session) -> dict[str, int]:
        rows = db.execute(select(Job.status, func.count(Job.id)).group_by(Job.status)).all()
        counts = {status: int(count) for status, count in rows}
        return {"queued": counts.get("queued", 0), "running": counts.get("running", 0), "succeeded": counts.get("succeeded", 0), "failed": counts.get("failed", 0), "total": sum(counts.values())}

    def recover_stale(self, db: Session, stale_minutes: int = 10) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
        jobs = db.scalars(select(Job).where(Job.status == "running", Job.locked_at < cutoff)).all()
        for job in jobs:
            job.status = "queued"
            job.locked_at = None
            job.locked_by = None
            job.last_error = "Recovered after worker timeout"
        if jobs:
            db.commit()
        return len(jobs)

    def claim(self, worker_id: str) -> str | None:
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            job = db.scalar(
                select(Job)
                .where(Job.status == "queued", Job.run_after <= now)
                .order_by(Job.run_after.asc(), Job.created_at.asc())
                .limit(1)
            )
            if not job:
                return None
            job.status = "running"
            job.attempts += 1
            job.locked_at = now
            job.locked_by = worker_id
            db.commit()
            return job.id
        finally:
            db.close()

    def execute(self, job_id: str) -> None:
        db = SessionLocal()
        try:
            job = db.get(Job, job_id)
            if not job:
                return
            try:
                result = self._run_job(db, job)
                job.status = "succeeded"
                job.result = result
                job.last_error = None
                job.completed_at = datetime.now(timezone.utc)
                job.locked_at = None
                job.locked_by = None
                db.commit()
            except Exception as exc:  # noqa: BLE001 - worker must convert failures into retry state
                logger.exception("Job %s failed", job.id)
                job.last_error = str(exc)[:2000]
                job.locked_at = None
                job.locked_by = None
                if job.attempts < job.max_attempts:
                    backoff = min(900, 2 ** max(job.attempts - 1, 0) * 10)
                    job.status = "queued"
                    job.run_after = datetime.now(timezone.utc) + timedelta(seconds=backoff)
                else:
                    job.status = "failed"
                    job.completed_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

    def _run_job(self, db: Session, job: Job) -> dict[str, Any]:
        if job.job_type == "jira_sync":
            ticket = db.get(Ticket, job.payload.get("ticket_id"))
            if not ticket:
                return {"status": "skipped", "reason": "Ticket no longer exists"}
            return sync_ticket_to_jira(db, ticket, force=True, comment=job.payload.get("comment"))
        if job.job_type == "sla_scan":
            return self._run_sla_scan(db)
        raise RuntimeError(f"Unknown job type: {job.job_type}")

    @staticmethod
    def _run_sla_scan(db: Session) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        tickets = db.scalars(select(Ticket).where(Ticket.status.notin_(["Resolved", "Closed"]), Ticket.sla_due_at < now)).all()
        created = 0
        for ticket in tickets:
            message = "SLA breached; review and escalate this ticket"
            already_logged = db.scalar(select(func.count(TicketEvent.id)).where(TicketEvent.ticket_id == ticket.id, TicketEvent.event_type == "sla_breach"))
            if not already_logged:
                db.add(TicketEvent(ticket_id=ticket.id, event_type="sla_breach", actor="Relay worker", message=message, visibility="internal"))
                created += 1
        if created:
            db.commit()
        return {"breached": len(tickets), "events_created": created}


class JobWorker:
    def __init__(self, queue: JobQueue | None = None, poll_seconds: float = 1.0) -> None:
        self.queue = queue or JobQueue()
        self.poll_seconds = poll_seconds
        self.worker_id = f"worker_{uuid.uuid4().hex[:8]}"
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, name="relay-job-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)

    def _run(self) -> None:
        recovery_db = SessionLocal()
        try:
            recovered = self.queue.recover_stale(recovery_db)
            if recovered:
                logger.warning("Recovered %s stale jobs", recovered)
        finally:
            recovery_db.close()
        next_sla_scan = 0.0
        while not self.stop_event.is_set():
            if time.time() >= next_sla_scan:
                db = SessionLocal()
                try:
                    self.queue.enqueue(
                        db,
                        "sla_scan",
                        {},
                        idempotency_key=f"sla-scan:{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H')}",
                    )
                finally:
                    db.close()
                next_sla_scan = time.time() + 300
            job_id = self.queue.claim(self.worker_id)
            if job_id:
                self.queue.execute(job_id)
            else:
                self.stop_event.wait(self.poll_seconds)


queue = JobQueue()
worker = JobWorker(queue=queue)


def dispatch_jira_sync(db: Session, ticket: Ticket, comment: str | None = None) -> dict[str, Any]:
    if ticket.requires_approval and not ticket.approved_by:
        return {"status": "blocked_by_policy", "provider": "jira", "error": "Approval required"}
    if settings.jira_auto_sync and settings.jira_base_url and settings.jira_email and settings.jira_api_token and settings.jira_project_key:
        comment_hash = hashlib.sha1((comment or "").encode()).hexdigest()[:10]
        idempotency_key = f"jira-sync:{ticket.id}:{ticket.status}:{comment_hash}"
        job = queue.enqueue(db, "jira_sync", {"ticket_id": ticket.id, "comment": comment}, idempotency_key=idempotency_key)
        return {"status": "queued", "provider": "jira", "job_id": job.id}
    return sync_ticket_to_jira(db, ticket, comment=comment)


def enqueue_sla_scan(db: Session) -> Job:
    return queue.enqueue(db, "sla_scan", {}, idempotency_key=f"sla-scan:{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H')}")
