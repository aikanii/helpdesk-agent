from __future__ import annotations

import os
from pathlib import Path

import pytest

TEST_DB = Path("test_helpdesk.db")
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["DATABASE_URL"] = "sqlite:///./test_helpdesk.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        login = test_client.post("/api/auth/login", json={"username": "admin@acme.co", "password": "relay-demo-2026"})
        assert login.status_code == 200
        test_client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
        yield test_client
    TEST_DB.unlink(missing_ok=True)


def test_authentication_and_profile(client):
    profile = client.get("/api/auth/me")
    assert profile.status_code == 200
    assert profile.json()["role"] == "admin"
    assert profile.json()["email"] == "admin@acme.co"


def test_health_and_seeded_dashboard(client):
    assert client.get("/api/health").status_code == 200
    stats = client.get("/api/stats").json()
    assert stats["open"] >= 1
    assert stats["escalated"] >= 1


def test_diagnose_without_creating_ticket(client):
    response = client.post(
        "/api/diagnose",
        json={"message": "My password is locked and I cannot sign in", "create_ticket": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "Account access"
    assert body["ticket"] is None
    assert body["evidence"]


def test_conversation_persists_two_messages(client):
    conversation = client.post("/api/conversations", json={}).json()
    response = client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"message": "Slack is slow for my team", "create_ticket": False},
    )
    assert response.status_code == 200
    detail = client.get(f"/api/conversations/{conversation['id']}").json()
    assert len(detail["messages"]) == 2
    assert detail["messages"][0]["role"] == "user"
    assert detail["messages"][1]["role"] == "assistant"


def test_knowledge_ingestion_and_feedback(client):
    document = client.post(
        "/api/docs",
        json={
            "title": "Test runbook",
            "content": "Use this test runbook to verify knowledge ingestion works correctly.",
            "category": "Testing",
        },
    )
    assert document.status_code == 200
    document_id = document.json()["id"]
    assert client.delete(f"/api/docs/{document_id}").status_code == 200

    feedback = client.post("/api/feedback", json={"run_id": "run_test", "rating": "helpful"})
    assert feedback.status_code == 200


def test_ticket_timeline_and_manual_note(client):
    ticket = client.get("/api/tickets").json()[0]
    events = client.get(f"/api/tickets/{ticket['id']}/events")
    assert events.status_code == 200
    note = client.post(
        f"/api/tickets/{ticket['id']}/events",
        json={"message": "Reviewed by automated API test", "actor": "Test Agent"},
    )
    assert note.status_code == 200
    assert note.json()["event_type"] == "note"
