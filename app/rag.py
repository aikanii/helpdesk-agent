from __future__ import annotations

import json
import re
from pathlib import Path
from dataclasses import dataclass

from .core import settings


@dataclass
class Document:
    id: str
    title: str
    content: str
    category: str
    updated: str


class DocumentationIndex:
    """Small lexical retriever for the MVP; replace with pgvector embeddings in production."""

    def __init__(self) -> None:
        path = settings.base_dir / "data" / "documents.json"
        self.documents = [Document(**item) for item in json.loads(path.read_text())]

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2}

    def search(self, query: str, limit: int = 4) -> list[dict]:
        query_tokens = self._tokens(query)
        scored: list[tuple[float, Document]] = []
        for doc in self.documents:
            doc_tokens = self._tokens(f"{doc.title} {doc.content} {doc.category}")
            overlap = query_tokens & doc_tokens
            # Title matches carry more weight than body matches.
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
                "id": doc.id,
                "title": doc.title,
                "excerpt": excerpt,
                "score": round(min(score / max(len(query_tokens), 1), 0.99), 2),
                "type": "Runbook",
                "category": doc.category,
                "content": doc.content,
                "updated": doc.updated,
            })
        return results

    def all(self) -> list[dict]:
        return [doc.__dict__ for doc in self.documents]


index = DocumentationIndex()
