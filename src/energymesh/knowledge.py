from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KnowledgeHit:
    source_id: str
    title: str
    score: float
    excerpt: str
    path: str


class KnowledgeBase:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).parent / "data" / "knowledge"

    def search(self, query: str, limit: int = 3) -> list[KnowledgeHit]:
        terms = self._terms(query)
        hits: list[KnowledgeHit] = []
        for path in sorted(self.root.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title = self._title(text, path)
            lower = text.lower()
            score: float = sum(lower.count(term) for term in terms)
            if score == 0:
                score = 0.2 if any(char in text for char in query[:12]) else 0
            if score <= 0:
                continue
            hits.append(
                KnowledgeHit(
                    source_id=path.stem,
                    title=title,
                    score=float(score),
                    excerpt=self._excerpt(text, terms),
                    path=str(path),
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[: max(1, min(limit, 10))]

    @staticmethod
    def _terms(query: str) -> list[str]:
        ascii_terms = re.findall(r"[a-zA-Z0-9_]+", query.lower())
        chinese_terms = re.findall(r"[\u4e00-\u9fff]{2,}", query)
        return [*ascii_terms, *chinese_terms]

    @staticmethod
    def _title(text: str, path: Path) -> str:
        first = text.splitlines()[0].strip() if text.splitlines() else ""
        return first.lstrip("# ").strip() or path.stem

    @staticmethod
    def _excerpt(text: str, terms: list[str]) -> str:
        compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
        lower = compact.lower()
        positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
        start = max(0, min(positions) - 60) if positions else 0
        return compact[start : start + 420]
