from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "talent-ranker"


class LocationPriority(BaseModel):
    locations: list[str] = Field(default_factory=list)
    remote_policy: Literal["onsite", "hybrid", "remote"] | None = None


class AvailabilityPriority(BaseModel):
    max_notice_period_days: int | None = Field(default=None, ge=0, le=365)
    target_start_date: str | None = None


class CompensationPriority(BaseModel):
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    minimum: float | None = Field(default=None, ge=0)
    maximum: float | None = Field(default=None, ge=0)
    period: Literal["hour", "month", "year"] | None = None

    @model_validator(mode="after")
    def validate_range(self):
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("compensation minimum cannot exceed maximum")
        return self


class HiringPriorities(BaseModel):
    must_have_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    must_have_requirements: list[str] = Field(default_factory=list)
    preferred_requirements: list[str] = Field(default_factory=list)
    minimum_years_experience: float | None = Field(default=None, ge=0, le=80)
    seniority: str | None = None
    location: LocationPriority = Field(default_factory=LocationPriority)
    availability: AvailabilityPriority = Field(default_factory=AvailabilityPriority)
    compensation: CompensationPriority = Field(default_factory=CompensationPriority)

    @model_validator(mode="after")
    def normalize_skills(self):
        self.must_have_skills = list(
            dict.fromkeys(skill.strip() for skill in self.must_have_skills if skill.strip())
        )
        must_have = {skill.casefold() for skill in self.must_have_skills}
        self.preferred_skills = list(
            dict.fromkeys(
                skill.strip()
                for skill in self.preferred_skills
                if skill.strip() and skill.strip().casefold() not in must_have
            )
        )
        return self


class HiringPriorityOverrides(BaseModel):
    must_have_skills: list[str] | None = None
    preferred_skills: list[str] | None = None
    must_have_requirements: list[str] | None = None
    preferred_requirements: list[str] | None = None
    minimum_years_experience: float | None = Field(default=None, ge=0, le=80)
    seniority: str | None = None
    location: LocationPriority | None = None
    availability: AvailabilityPriority | None = None
    compensation: CompensationPriority | None = None


class CalibrateJobRequest(BaseModel):
    job_id: str = Field(min_length=1)
    job_description: str = Field(min_length=20, max_length=50000)
    overrides: HiringPriorityOverrides | None = None


class UpdateJobProfileRequest(BaseModel):
    priorities: HiringPriorities


class ApproveJobProfileRequest(BaseModel):
    approved_by: str = Field(min_length=1)


class JobProfileResponse(BaseModel):
    profile_version_id: UUID
    job_id: str
    version: int
    status: Literal["draft", "approved", "superseded"]
    job_description: str
    priorities: HiringPriorities
    created_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None
    calibration_metadata: dict = Field(default_factory=dict)


class RankRequest(BaseModel):
    job_id: str = Field(min_length=1)
    job_profile_version_id: UUID
    top_k: int = Field(default=100, ge=1, le=1000)


class CandidateScore(BaseModel):
    candidate_id: str
    rank: int
    score: float
    score_components: dict[str, float]
    evidence: list[str]
    reasoning: str
    requirement_evidence: list[dict] = Field(default_factory=list)


class RankResponse(BaseModel):
    run_id: str
    results: list[CandidateScore]


class CandidateEvidenceResponse(BaseModel):
    run_id: str
    job_id: str
    job_profile_version_id: UUID | None = None
    candidate_id: str
    rank: int
    score: float
    score_components: dict[str, float]
    evidence: list[str]
    reasoning: str
    requirement_evidence: list[dict] = Field(default_factory=list)
    created_at: datetime
