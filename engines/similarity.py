"""Deterministic duplicate, near-duplicate and story clustering (no LLM involved)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOP = frozenset("a an the of to in on for and or by with at from is are was were be as it its that this "
                  "has have had will would said says say".split())

NEAR_DUPLICATE = 0.80   # shingle Jaccard at or above this: the same text republished
SAME_STORY = 0.30       # combined similarity at or above this: same story, different write-up
WINDOW_HOURS = 72


def tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOP]


def shingles(text: str, k: int = 3) -> set[tuple[str, ...]]:
    t = tokens(text)
    if len(t) < k:
        return {tuple(t)} if t else set()
    return {tuple(t[i:i + k]) for i in range(len(t) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True)
class Doc:
    item_id: int
    title: str
    text: str
    published_at_utc: str | None = None
    entities: frozenset[str] = frozenset()


def similarity(a: Doc, b: Doc) -> tuple[float, bool]:
    """Return (score 0..1, is_near_duplicate). Title words, body shingles and shared entities."""
    body = jaccard(shingles(a.text), shingles(b.text))
    if body >= NEAR_DUPLICATE:
        return round(body, 4), True
    title = jaccard(set(tokens(a.title)), set(tokens(b.title)))
    ent = jaccard(set(a.entities), set(b.entities)) if a.entities and b.entities else 0.0
    words = jaccard(set(tokens(a.text)), set(tokens(b.text)))
    score = 0.35 * title + 0.35 * words + 0.30 * ent
    return round(min(score, 1.0), 4), False


def _hours_apart(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    da = datetime.fromisoformat(a.replace("Z", "+00:00"))
    db = datetime.fromisoformat(b.replace("Z", "+00:00"))
    return abs((da - db).total_seconds()) / 3600


@dataclass
class Cluster:
    members: list[int]
    near_duplicates: dict[int, int]  # item -> item it duplicates
    links: dict[tuple[int, int], float]


def cluster(docs: list[Doc]) -> list[Cluster]:
    """Single-link clustering within a time window. Order-independent and reproducible."""
    docs = sorted(docs, key=lambda d: d.item_id)
    parent = {d.item_id: d.item_id for d in docs}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    links: dict[tuple[int, int], float] = {}
    dups: dict[int, int] = {}
    for i, a in enumerate(docs):
        for b in docs[i + 1:]:
            if _hours_apart(a.published_at_utc, b.published_at_utc) > WINDOW_HOURS:
                continue
            score, near = similarity(a, b)
            if near:
                dups.setdefault(b.item_id, a.item_id)
            if near or score >= SAME_STORY:
                links[(a.item_id, b.item_id)] = score
                ra, rb = find(a.item_id), find(b.item_id)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    groups: dict[int, list[int]] = {}
    for d in docs:
        groups.setdefault(find(d.item_id), []).append(d.item_id)
    out = []
    for members in groups.values():
        ms = set(members)
        out.append(Cluster(members, {k: v for k, v in dups.items() if k in ms},
                           {k: v for k, v in links.items() if k[0] in ms}))
    return sorted(out, key=lambda c: c.members[0])
