from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .core import settings
from .models import KnowledgeChunk, KnowledgeDocument

EMBEDDING_DIMENSIONS = 1536
ROLE_RANK = {"requester": 0, "agent": 1, "manager": 2, "admin": 3}


@dataclass
class LegacyDocument:
    id: str
    title: str
    content: str
    category: str
    updated: str
    source: str = "Seed runbook"


class EmbeddingService:
    def __init__(self) -> None:
        self.client = None
        if settings.openai_api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=settings.openai_api_key)
            except ImportError:
                pass

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.client:
            try:
                response = self.client.embeddings.create(model=settings.embedding_model, input=texts)
                return [item.embedding for item in response.data]
            except Exception:
                # Keep local development usable if the provider is unavailable.
                pass
        return [self._local_embedding(text) for text in texts]

    @staticmethod
    def _local_embedding(text: str) -> list[float]:
        """Deterministic offline fallback; use provider embeddings in production."""
        vector = [0.0] * EMBEDDING_DIMENSIONS
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
            vector[index] += 1.0
        magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [round(value / magnitude, 8) for value in vector]


class DocumentationIndex:
    """Postgres/pgvector-backed RAG index with an offline SQLite fallback."""

    def __init__(self) -> None:
        path = settings.base_dir / "data" / "documents.json"
        self.legacy_documents = [LegacyDocument(**item) for item in json.loads(path.read_text())]
        self.embeddings = EmbeddingService()

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2}

    @staticmethod
    def _chunk_text(content: str, max_chars: int = 900, overlap_chars: int = 120) -> list[str]:
        normalized = re.sub(r"\s+", " ", content).strip()
        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(start + max_chars, len(normalized))
            if end < len(normalized):
                boundary = normalized.rfind(" ", start + max_chars // 2, end)
                if boundary > start:
                    end = boundary
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            start = max(end - overlap_chars, start + 1)
        return chunks

    @staticmethod
    def _visible_min_roles(user_role: str) -> list[str]:
        maximum = ROLE_RANK.get(user_role, 0)
        return [role for role, rank in ROLE_RANK.items() if rank <= maximum]

    def ensure_seeded(self, db: Session) -> None:
        if db.scalar(select(func.count(KnowledgeDocument.id))) > 0:
            return
        for document in self.legacy_documents:
            self.ingest(
                db,
                title=document.title,
                content=document.content,
                category=document.category,
                source=document.source,
                source_url=None,
                min_role="requester",
                created_by="system",
            )

    def ingest(
        self,
        db: Session,
        title: str,
        content: str,
        category: str = "General",
        source: str = "Uploaded runbook",
        source_url: str | None = None,
        min_role: str = "requester",
        created_by: str = "system",
    ) -> dict[str, Any]:
        if min_role not in ROLE_RANK:
            min_role = "requester"
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        existing = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.content_hash == content_hash))
        if existing:
            return self.serialize_document(db, existing)
        chunks = self._chunk_text(content)
        embeddings = self.embeddings.embed(chunks)
        document = KnowledgeDocument(
            id=f"doc-{uuid.uuid4().hex[:10]}",
            title=title.strip(),
            category=category.strip() or "General",
            source=source.strip() or "Uploaded runbook",
            source_url=source_url.strip() if source_url else None,
            min_role=min_role,
            status="indexed",
            chunk_count=len(chunks),
            created_by=created_by,
            content_hash=content_hash,
        )
        db.add(document)
        db.flush()
        for chunk_index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            db.add(KnowledgeChunk(
                document_id=document.id,
                chunk_index=chunk_index,
                content=chunk,
                token_count=len(self._tokens(chunk)),
                embedding=embedding,
                chunk_metadata={"category": document.category, "source": document.source},
            ))
        db.commit()
        db.refresh(document)
        return self.serialize_document(db, document)

    def search(self, query: str | None, db: Session | None = None, limit: int = 4, user_role: str = "requester", category: str | None = None) -> list[dict[str, Any]]:
        if db is None:
            return self._legacy_search(query, limit)
        self.ensure_seeded(db)
        query = query or ""
        allowed_roles = self._visible_min_roles(user_role)
        try:
            from sqlalchemy.engine import Engine
            is_postgres = db.get_bind().dialect.name == "postgresql"
            if is_postgres:
                query_embedding = self.embeddings.embed([query])[0]
                distance = KnowledgeChunk.embedding.cosine_distance(query_embedding)
                vector_query = (
                    select(KnowledgeChunk, KnowledgeDocument, distance.label("distance"))
                    .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                    .where(KnowledgeDocument.min_role.in_(allowed_roles))
                    .where(KnowledgeDocument.status == "indexed")
                )
                if category:
                    vector_query = vector_query.where(KnowledgeDocument.category == category)
                rows = db.execute(vector_query.order_by(distance).limit(limit)).all()
                return [self._evidence(chunk, document, max(0.0, 1.0 - float(distance_value))) for chunk, document, distance_value in rows]
        except Exception:
            # If pgvector is temporarily unavailable, fall back to lexical retrieval.
            pass
        return self._lexical_search(db, query, allowed_roles, limit, category)

    def all(self, db: Session | None = None, user_role: str = "requester", category: str | None = None) -> list[dict[str, Any]]:
        if db is None:
            return [asdict(document) for document in self.legacy_documents]
        self.ensure_seeded(db)
        allowed_roles = self._visible_min_roles(user_role)
        document_query = select(KnowledgeDocument).where(KnowledgeDocument.min_role.in_(allowed_roles))
        if category:
            document_query = document_query.where(KnowledgeDocument.category == category)
        documents = db.scalars(document_query.order_by(KnowledgeDocument.updated_at.desc())).all()
        return [self.serialize_document(db, document) for document in documents]

    def get(self, db: Session, document_id: str) -> dict[str, Any] | None:
        self.ensure_seeded(db)
        document = db.get(KnowledgeDocument, document_id)
        return self.serialize_document(db, document) if document else None

    def delete(self, db: Session, document_id: str) -> bool:
        document = db.get(KnowledgeDocument, document_id)
        if not document:
            return False
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document_id).delete(synchronize_session=False)
        db.delete(document)
        db.commit()
        return True

    def serialize_document(self, db: Session, document: KnowledgeDocument) -> dict[str, Any]:
        chunks = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id).order_by(KnowledgeChunk.chunk_index)).all()
        return {
            "id": document.id,
            "title": document.title,
            "content": "\n\n".join(chunk.content for chunk in chunks),
            "category": document.category,
            "updated": document.updated_at.strftime("%b %d, %Y"),
            "source": document.source,
            "source_url": document.source_url,
            "min_role": document.min_role,
            "status": document.status,
            "chunk_count": document.chunk_count,
        }

    def _lexical_search(self, db: Session, query: str, allowed_roles: list[str], limit: int, category: str | None = None) -> list[dict[str, Any]]:
        query_tokens = self._tokens(query)
        lexical_query = (
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeDocument.min_role.in_(allowed_roles))
            .where(KnowledgeDocument.status == "indexed")
        )
        if category:
            lexical_query = lexical_query.where(KnowledgeDocument.category == category)
        chunks = db.execute(lexical_query).all()
        scored: list[tuple[float, KnowledgeChunk, KnowledgeDocument]] = []
        for chunk, document in chunks:
            overlap = query_tokens & self._tokens(f"{document.title} {document.category} {chunk.content}")
            title_overlap = query_tokens & self._tokens(document.title)
            score = len(overlap) + len(title_overlap) * 1.5
            if score:
                scored.append((score, chunk, document))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [self._evidence(chunk, document, min(score / max(len(query_tokens), 1), 0.99)) for score, chunk, document in scored[:limit]]

    def _legacy_search(self, query: str | None, limit: int) -> list[dict[str, Any]]:
        query_tokens = self._tokens(query or "")
        scored: list[tuple[float, LegacyDocument]] = []
        for document in self.legacy_documents:
            overlap = query_tokens & self._tokens(f"{document.title} {document.content} {document.category}")
            title_overlap = query_tokens & self._tokens(document.title)
            score = len(overlap) + len(title_overlap) * 1.5
            if score:
                scored.append((score, document))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [{**asdict(document), "excerpt": document.content[:190].rstrip() + ("…" if len(document.content) > 190 else ""), "score": round(min(score / max(len(query_tokens), 1), 0.99), 2), "type": "Runbook"} for score, document in scored[:limit]]

    @staticmethod
    def _evidence(chunk: KnowledgeChunk, document: KnowledgeDocument, score: float) -> dict[str, Any]:
        excerpt = chunk.content[:260].rstrip() + ("…" if len(chunk.content) > 260 else "")
        return {
            "id": document.id,
            "title": document.title,
            "excerpt": excerpt,
            "score": round(score, 3),
            "type": "Runbook",
            "category": document.category,
            "content": chunk.content,
            "source": document.source,
            "source_url": document.source_url,
            "updated": document.updated_at.strftime("%b %d, %Y"),
            "chunk_index": chunk.chunk_index,
        }


index = DocumentationIndex()
