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


class CriterionRelevanceScoringPolicy:
    """Rank by relative BGE passage relevance, without treating it as proof of fit."""

    def score(self, matches: list[dict]) -> ScoreDecision:
        must = [row["semantic_percentile"] for row in matches
                if row["category"].startswith("must_have")]
        preferred = [row["semantic_percentile"] for row in matches
                     if row["category"].startswith("preferred")]
        role = [row["semantic_percentile"] for row in matches
                if row["category"] == "role_responsibilities"]
        must_mean = sum(must) / len(must) if must else 0.0
        preferred_mean = sum(preferred) / len(preferred) if preferred else 0.0
        role_mean = sum(role) / len(role) if role else 0.0
        primary = must_mean if must else preferred_mean if preferred else role_mean
        components = {
            "must_have_relevance": round(must_mean, 6),
            "preferred_relevance": round(preferred_mean, 6),
        }
        if role:
            components["role_relevance"] = round(role_mean, 6)
        return ScoreDecision(score=round(primary, 6), components=components)
