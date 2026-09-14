from __future__ import annotations

import json
from typing import Any

from .core import settings


class LLMService:
    """Uses OpenAI when configured, with a deterministic fallback for local demos."""

    def __init__(self) -> None:
        self.client = None
        if settings.openai_api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=settings.openai_api_key)
            except ImportError:
                pass

    def classify(self, message: str, context: list[dict[str, Any]]) -> dict[str, Any]:
        if self.client:
            prompt = {
                "role": "user",
                "content": (
                    "Classify this IT helpdesk issue. Return JSON with intent, category, priority, "
                    "confidence (0-100), summary, and actions (array of label/detail).\n"
                    f"Issue: {message}\nDocumentation context: {json.dumps(context)}"
                ),
            }
            try:
                response = self.client.chat.completions.create(
                    model=settings.openai_model,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": "You are a precise IT service desk triage agent."},
                        prompt,
                    ],
                )
                return json.loads(response.choices[0].message.content)
            except Exception:
                pass
        return self._fallback(message, context)

    def _fallback(self, message: str, context: list[dict[str, Any]]) -> dict[str, Any]:
        text = message.lower()
        if any(word in text for word in ("vpn", "remote", "tunnel", "forti")):
            intent, category = "VPN connectivity", "Access & Identity"
            summary = "The user is unable to establish a secure remote connection."
            actions = [
                {"label": "Verify account access", "detail": "Confirm the account is active and MFA is completing successfully."},
                {"label": "Refresh VPN profile", "detail": "Sign out of the VPN client, remove the stale profile, then reconnect with the current profile."},
                {"label": "Capture client logs", "detail": "If the tunnel still fails, collect the latest VPN logs for network operations."},
            ]
        elif any(word in text for word in ("password", "login", "sign in", "locked", "mfa")):
            intent, category = "Account access", "Access & Identity"
            summary = "The user is blocked from signing in or completing authentication."
            actions = [
                {"label": "Check account status", "detail": "Confirm the identity account is active and not locked by repeated attempts."},
                {"label": "Use password reset", "detail": "Start a self-service reset and complete the MFA verification step."},
                {"label": "Escalate identity review", "detail": "Route to Identity Operations if MFA remains unavailable."},
            ]
        elif any(word in text for word in ("slow", "down", "error", "crash", "outage", "not working")):
            intent, category = "Service degradation", "Service Health"
            summary = "The report suggests a service or application is degraded."
            actions = [
                {"label": "Check service status", "detail": "Compare the symptom with current service health and active incidents."},
                {"label": "Collect scope", "detail": "Confirm whether the issue affects one user, a team, or the whole organization."},
                {"label": "Escalate to owner", "detail": "Attach timestamps, screenshots, and reproduction steps for the service owner."},
            ]
        else:
            intent, category = "General IT support", "General"
            summary = "The agent found a likely support request that needs guided triage."
            actions = [
                {"label": "Clarify the symptom", "detail": "Ask for the exact error, affected device, and when the issue started."},
                {"label": "Try the relevant runbook", "detail": "Follow the closest documentation match and record the result."},
                {"label": "Create a support ticket", "detail": "Escalate with the user impact and troubleshooting already completed."},
            ]
        priority = "High" if any(word in text for word in ("everyone", "outage", "urgent", "production")) else "Medium"
        return {
            "intent": intent,
            "category": category,
            "priority": priority,
            "confidence": min(96, 70 + len(context) * 5),
            "summary": summary,
            "actions": actions,
        }


llm = LLMService()
