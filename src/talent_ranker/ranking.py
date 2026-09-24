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


def source_platform_signals(metadata: dict) -> dict:
    signals = metadata.get("source_platform_signals") or metadata.get("linkedin_signals") or {}
    if "linkedin" in signals and isinstance(signals["linkedin"], dict):
        return signals["linkedin"]
    return signals if isinstance(signals, dict) else {}


def quality_multiplier(metadata: dict) -> tuple[float, list[str]]:
    """Apply only job-related availability and evidence-quality checks."""
    multiplier, concerns = 1.0, []
    signals = source_platform_signals(metadata)
    years = metadata.get("years_experience")
    claimed_skill_months = metadata.get("max_claimed_skill_months")
    if (
        years is not None
        and claimed_skill_months is not None
        and claimed_skill_months > years * 12 + 18
    ):
        multiplier *= 0.35
        concerns.append("skill duration conflicts with stated career length")
    if metadata.get("timeline_overlap_months", 0) > 24:
        multiplier *= 0.55
        concerns.append("career timeline needs verification")
    if metadata.get("months_since_active", 0) > 6:
        multiplier *= 0.88
        concerns.append("low recent availability signal")
    response = metadata.get("recruiter_response_rate", signals.get("recruiter_response_rate"))
    if response is not None:
        multiplier *= 0.9 + 0.1 * max(0.0, min(1.0, float(response)))
    return multiplier, concerns


def final_score(
    rrf: float,
    reranker_logit: float,
    metadata: dict,
    calibrated_priority: float | None = None,
) -> tuple[float, dict, list[str]]:
    semantic = sigmoid(reranker_logit)
    # RRF values are about 0.01-0.02 with k=60; normalize into a bounded feature.
    retrieval = min(1.0, rrf * 60.0)
    if calibrated_priority is None:
        fit = 0.72 * semantic + 0.28 * retrieval
    else:
        fit = 0.55 * semantic + 0.20 * retrieval + 0.25 * calibrated_priority
    multiplier, concerns = quality_multiplier(metadata)
    score = fit * multiplier
    return (
        score,
        {
            "semantic": round(semantic, 6),
            "retrieval": round(retrieval, 6),
            **(
                {"calibrated_priority": round(calibrated_priority, 6)}
                if calibrated_priority is not None
                else {}
            ),
            "quality_multiplier": round(multiplier, 6),
        },
        concerns,
    )


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
