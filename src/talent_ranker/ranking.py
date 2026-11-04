from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from .privacy import redact_pii


@dataclass
class RetrievedCandidate:
    candidate_id: str
    chunks: list[str] = field(default_factory=list)
    dense_rank: int | None = None
    lexical_rank: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RankedCandidate:
    candidate_id: str
    score: float
    components: dict[str, float]
    evidence: list[str]
    reasoning: str
    requirement_evidence: list[dict] = field(default_factory=list)


def reciprocal_rank_fusion(
    dense_ids: Iterable[str], lexical_ids: Iterable[str], k: int = 60
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for weight, ids in ((0.55, dense_ids), (0.45, lexical_ids)):
        for rank, candidate_id in enumerate(ids, 1):
            scores[candidate_id] = scores.get(candidate_id, 0.0) + weight / (k + rank)
    return scores


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))


def evidence_snippet(text: str, jd_terms: set[str], limit: int = 220) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    best = max(sentences, key=lambda s: len(set(re.findall(r"[a-z0-9]+", s.lower())) & jd_terms))
    return redact_pii(best)[:limit].strip()


def build_reasoning(evidence: list[str], concerns: list[str], score: float) -> str:
    fact = evidence[0] if evidence else "No direct requirement evidence was found"
    fact = redact_pii(fact).rstrip(".") + "."
    if concerns:
        return f"{fact} Concern: {concerns[0]}."
    if score >= 0.75:
        return f"{fact} Strong overall match across lexical and semantic retrieval."
    return f"{fact} Relevant evidence exists, but the overall match is less complete than higher ranks."
