"""Lesson memory with a pluggable similarity backend.

The default backend is a dependency-free token-overlap (Jaccard-ish) scorer,
which is enough to surface "you've seen a setup like this before" lessons. The
``Similarity`` protocol lets you swap in a real embedding model later without
touching callers.
"""

from __future__ import annotations

import re
from typing import Protocol

from xdd.domain import Lesson
from xdd.storage import Repository

_TOKEN = re.compile(r"[a-z0-9]+")


class Similarity(Protocol):
    def score(self, query: str, doc: str) -> float:
        ...


class TokenOverlap:
    def score(self, query: str, doc: str) -> float:
        q = set(_TOKEN.findall(query.lower()))
        d = set(_TOKEN.findall(doc.lower()))
        if not q or not d:
            return 0.0
        return len(q & d) / len(q | d)


class MemoryStore:
    def __init__(self, repo: Repository, similarity: Similarity | None = None) -> None:
        self._repo = repo
        self._sim = similarity or TokenOverlap()

    def add(self, lesson: Lesson) -> None:
        self._repo.add_lesson(lesson)

    def retrieve(self, query: str, *, ticker: str | None = None, k: int = 3) -> list[Lesson]:
        """Return the ``k`` most relevant lessons for a query.

        Lessons about the same ticker get a relevance bump — a prior mistake on
        the same name is the most actionable memory.
        """
        lessons = self._repo.all_lessons()
        scored: list[tuple[float, Lesson]] = []
        for lesson in lessons:
            score = self._sim.score(query, lesson.text)
            if ticker and lesson.ticker == ticker:
                score += 0.25
            if score > 0:
                scored.append((score, lesson))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [lesson for _, lesson in scored[:k]]
