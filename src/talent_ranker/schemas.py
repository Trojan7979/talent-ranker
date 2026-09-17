from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "talent-ranker"


class RankRequest(BaseModel):
    job_id: str = Field(min_length=1)
    job_description: str = Field(min_length=20)
    top_k: int = Field(default=100, ge=1, le=1000)


class CandidateScore(BaseModel):
    candidate_id: str
    rank: int
    score: float
    score_components: dict[str, float]
    evidence: list[str]
    reasoning: str


class RankResponse(BaseModel):
    run_id: str
    results: list[CandidateScore]
