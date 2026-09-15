from __future__ import annotations

import base64
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..core import settings


class JiraError(RuntimeError):
    pass


def _adf_text(text: str) -> dict[str, Any]:
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


class JiraClient:
    """Minimal Jira Cloud REST client using email + API token authentication."""

    provider = "jira"

    @property
    def configured(self) -> bool:
        return all((settings.jira_base_url, settings.jira_email, settings.jira_api_token, settings.jira_project_key))

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.configured:
            raise JiraError("Jira integration is not configured")
        token = base64.b64encode(f"{settings.jira_email}:{settings.jira_api_token}".encode()).decode()
        request = Request(
            f"{settings.jira_base_url}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers={
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Relay-Helpdesk/0.1",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:600]
            raise JiraError(f"Jira API returned {exc.code}: {detail}") from exc
        except URLError as exc:
            raise JiraError(f"Unable to reach Jira: {exc.reason}") from exc
        except TimeoutError as exc:
            raise JiraError("Jira request timed out") from exc

    def test_connection(self) -> dict[str, Any]:
        user = self._request("GET", "/rest/api/3/myself")
        return {"account_id": user.get("accountId"), "display_name": user.get("displayName"), "email": user.get("emailAddress")}

    def create_issue(self, ticket: Any) -> dict[str, str]:
        description = (
            f"Reported by: {ticket.requester_email or 'Unknown'}\n\n"
            f"{ticket.description}\n\n"
            f"Relay category: {ticket.category}\n"
            f"Relay priority: {ticket.priority}\n"
        )
        response = self._request("POST", "/rest/api/3/issue", {
            "fields": {
                "project": {"key": settings.jira_project_key},
                "summary": f"[{ticket.ticket_number}] {ticket.title}",
                "description": _adf_text(description),
                "issuetype": {"name": settings.jira_issue_type},
                "priority": {"name": self._jira_priority(ticket.priority)},
                "labels": ["relay", "ai-helpdesk"],
            }
        })
        key = response.get("key")
        if not key:
            raise JiraError("Jira did not return an issue key")
        return {"id": key, "url": f"{settings.jira_base_url}/browse/{key}"}

    def add_comment(self, issue_key: str, message: str) -> None:
        self._request("POST", f"/rest/api/3/issue/{issue_key}/comment", {"body": _adf_text(message)})

    def transition(self, issue_key: str, target_status: str) -> None:
        transitions = self._request("GET", f"/rest/api/3/issue/{issue_key}/transitions").get("transitions", [])
        target = target_status.lower()
        match = next((item for item in transitions if item.get("name", "").lower() == target or item.get("to", {}).get("name", "").lower() == target), None)
        if match:
            self._request("POST", f"/rest/api/3/issue/{issue_key}/transitions", {"transition": {"id": match["id"]}})

    def sync_status(self, issue_key: str, internal_status: str) -> None:
        mapping = {"Open": "Open", "In progress": "In Progress", "Pending": "Waiting for customer", "Escalated": "In Progress", "Needs review": "Open", "Resolved": "Done", "Closed": "Done", "Reopened": "In Progress"}
        self.transition(issue_key, mapping.get(internal_status, "Open"))

    @staticmethod
    def _jira_priority(priority: str) -> str:
        return {"High": "High", "Medium": "Medium", "Low": "Low"}.get(priority, "Medium")


jira = JiraClient()
