# Relay — AI IT Helpdesk Agent

Relay is a small, production-shaped MVP for an AI IT helpdesk agent. It diagnoses user issues, retrieves relevant runbooks, recommends next steps, and creates or escalates tickets.

## What is included

- **Agent orchestration:** normalize → retrieve → classify → recommend → create and route a ticket.
- **RAG:** a lightweight lexical retriever over `app/data/documents.json`; the seam is isolated in `app/rag.py` so it can be replaced by embeddings + pgvector.
- **LLM integration:** OpenAI JSON-mode classification when `OPENAI_API_KEY` is present, with a deterministic local fallback so the demo works without credentials.
- **FastAPI APIs:** diagnosis, ticket CRUD/status, documentation search, health, and dashboard stats.
- **PostgreSQL-ready persistence:** SQLAlchemy models work with PostgreSQL via `DATABASE_URL`; local runs default to SQLite for zero-setup development.
- **Operator UI:** responsive dashboard with queue, system pulse, knowledge base, and a live diagnosis panel.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. The first diagnosis is ready to run immediately; no API key is required.

## Run with PostgreSQL

```bash
docker compose up --build
```

To enable the real LLM classifier, copy `.env.example` to `.env`, add `OPENAI_API_KEY`, and restart the API container. Without a key, Relay uses the local fallback classifier.

## API quick reference

- `POST /api/diagnose` — run the helpdesk agent and optionally create a ticket.
- `GET /api/tickets` — list tickets with `status`, `priority`, and `q` filters.
- `POST /api/tickets` — create a manual ticket.
- `PATCH /api/tickets/{id}/status?status=Resolved` — update workflow status.
- `GET /api/docs?q=vpn` — search runbooks.
- `GET /api/stats` — dashboard metrics.
- `GET /docs` — interactive OpenAPI docs.

## Next production steps

1. Add document ingestion and chunking into PostgreSQL + pgvector.
2. Add SSO/RBAC and redact secrets/PII before LLM calls.
3. Add connectors for Jira, Zendesk, Slack, and the identity provider.
4. Add approval gates for high-impact actions and an immutable agent audit log.
5. Add evaluation sets for intent classification, retrieval quality, and safe escalation.
