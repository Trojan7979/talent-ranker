from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ScoreThreshold(BaseModel):
    kind: Literal["score_threshold"]
    value: float = Field(ge=0, le=1, allow_inf_nan=False)


class TopN(BaseModel):
    kind: Literal["top_n"]
    value: int = Field(ge=1, le=10000)


class RankCutoff(BaseModel):
    kind: Literal["rank_cutoff"]
    value: int = Field(ge=1, le=10000)


SelectionRule = Annotated[ScoreThreshold | TopN | RankCutoff, Field(discriminator="kind")]


class SelectionRequest(BaseModel):
    job_id: str = Field(min_length=1)
    ranking_run_id: UUID | None = None
    rule: SelectionRule


class CandidatePreview(BaseModel):
    candidate_id: str
    rank: int
    score: float
    has_contact: bool


class SelectionResponse(BaseModel):
    job_id: str
    ranking_run_id: UUID
    job_profile_version_id: UUID
    rule: SelectionRule
    candidates: list[CandidatePreview]
    matching_count: int
