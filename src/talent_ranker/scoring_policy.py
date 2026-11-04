"""Explicit, replaceable policies for turning model signals into ranking scores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .ranking import sigmoid


@dataclass(frozen=True)
class ScoreDecision:
    score: float
    components: dict[str, float]
    concerns: tuple[str, ...] = ()


class CandidateScoringPolicy(Protocol):
    def score(self, reranker_logit: float) -> ScoreDecision: ...


class SemanticRelevanceScoringPolicy:
    """Use the cross-encoder's relevance directly; retrieval only builds the pool."""

    def score(self, reranker_logit: float) -> ScoreDecision:
        relevance = sigmoid(reranker_logit)
        return ScoreDecision(
            score=relevance,
            components={"semantic_relevance": round(relevance, 6)},
        )
