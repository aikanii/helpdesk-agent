from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from dataclasses import asdict, dataclass
from datetime import datetime

from .core import settings


@dataclass
class Document:
    id: str
    title: str
    content: str
    category: str
    updated: str
    source: str = "Seed runbook"


class DocumentationIndex:
    """Small lexical retriever for the MVP; replace with pgvector embeddings in production."""

    def __init__(self) -> None:
        self.path = settings.base_dir / "data" / "documents.json"
        self.documents: list[Document] = []
        self.reload()

    def reload(self) -> None:
        self.documents = [Document(**item) for item in json.loads(self.path.read_text())]

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2}

    def search(self, query: str | None, limit: int = 4) -> list[dict]:
        if not query:
            return [asdict(doc) for doc in self.documents[:limit]]
        query_tokens = self._tokens(query)
        scored: list[tuple[float, Document]] = []
        for doc in self.documents:
            doc_tokens = self._tokens(f"{doc.title} {doc.content} {doc.category}")
            overlap = query_tokens & doc_tokens
            title_overlap = query_tokens & self._tokens(doc.title)
            score = len(overlap) + (len(title_overlap) * 1.5)
            if score:
                scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        results = []
        for score, doc in scored[:limit]:
            excerpt = doc.content[:190].rstrip()
            if len(doc.content) > 190:
                excerpt += "…"
            results.append({
                **asdict(doc),
                "excerpt": excerpt,
                "score": round(min(score / max(len(query_tokens), 1), 0.99), 2),
                "type": "Runbook",
            })
        return results

    def all(self) -> list[dict]:
        return [asdict(doc) for doc in self.documents]

    def add(self, title: str, content: str, category: str = "General", source: str = "Uploaded runbook") -> dict:
        document = Document(
            id=f"doc-{uuid.uuid4().hex[:8]}",
            title=title.strip(),
            content=content.strip(),
            category=category.strip() or "General",
            updated=datetime.now().strftime("%b %d, %Y"),
            source=source.strip() or "Uploaded runbook",
        )
        self.documents.append(document)
        self._persist()
        return asdict(document)

    def delete(self, doc_id: str) -> bool:
        original_count = len(self.documents)
        self.documents = [doc for doc in self.documents if doc.id != doc_id]
        if len(self.documents) == original_count:
            return False
        self._persist()
        return True

    def _persist(self) -> None:
        self.path.write_text(json.dumps([asdict(doc) for doc in self.documents], indent=2) + "\n")


index = DocumentationIndex()
