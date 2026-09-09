from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from agentictriage.models import RetrievedChunk

_TOKEN = re.compile(r"[a-z0-9]+")


def rank_chunks(
    query: str,
    chunks: Sequence[RetrievedChunk],
    *,
    tenant_id: str,
    limit: int = 5,
) -> list[RetrievedChunk]:
    """Small deterministic BM25-like reference implementation for fixtures/local use."""
    owned = [chunk for chunk in chunks if chunk.tenant_id == tenant_id]
    query_terms = Counter(_TOKEN.findall(query.lower()))
    if not query_terms or not owned:
        return []
    average_length = sum(len(_TOKEN.findall(c.content.lower())) for c in owned) / len(owned)
    scored: list[RetrievedChunk] = []
    for chunk in owned:
        terms = Counter(_TOKEN.findall(chunk.content.lower()))
        length = max(sum(terms.values()), 1)
        score = 0.0
        for term, query_frequency in query_terms.items():
            document_frequency = sum(term in _TOKEN.findall(c.content.lower()) for c in owned)
            inverse_frequency = math.log(
                1 + (len(owned) - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            frequency = terms[term]
            denominator = frequency + 1.2 * (0.25 + 0.75 * length / max(average_length, 1))
            score += (
                query_frequency
                * inverse_frequency
                * (frequency * 2.2 / denominator if denominator else 0)
            )
        if score > 0:
            scored.append(chunk.model_copy(update={"score": score}))
    return sorted(scored, key=lambda item: (-item.score, item.id))[:limit]
