from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field


def _valid_template(value: str) -> str:
    if value.count("{screening_link}") != 1:
        raise ValueError("message template needs exactly one {screening_link}")
    return value


ScreeningTemplate = Annotated[
    str, Field(min_length=1, max_length=20000), AfterValidator(_valid_template)
]

from .questions import JobQuestions
from .selection import SelectionRule


class CreateJobConfigRequest(BaseModel):
    job_profile_version_id: UUID
    questions: JobQuestions


class JobConfigResponse(BaseModel):
    id: UUID
    job_id: str
    job_profile_version_id: UUID
    version: int
    questions: JobQuestions
    policy_version: str
    created_by: str
    created_at: datetime


class ContactRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    source: str = Field(min_length=1, max_length=100)
    source_reference: str | None = None
    contactable: bool = True


class ContactResponse(ContactRequest):
    candidate_id: str
    updated_by: str
    updated_at: datetime


class CreateCampaignRequest(BaseModel):
    job_id: str = Field(min_length=1)
    ranking_run_id: UUID
    config_id: UUID
    rule: SelectionRule
    message_template: ScreeningTemplate
    expiry_hours: int = Field(default=48, ge=1, le=720)


class EditCampaignRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    final_candidate_ids: list[str] = Field(min_length=1, max_length=1000)
    message_template: ScreeningTemplate


class ApproveCampaignRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class CampaignResponse(BaseModel):
    id: UUID
    job_id: str
    ranking_run_id: UUID
    job_profile_version_id: UUID
    config_id: UUID
    selection_rule: SelectionRule
    proposed_candidate_ids: list[str]
    final_candidate_ids: list[str] | None
    message_template: str
    expiry_hours: int
    status: Literal["proposed", "approved", "rejected"]
    revision: int
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime


class CampaignSummary(BaseModel):
    id: UUID
    job_id: str
    ranking_run_id: UUID
    status: Literal["proposed", "approved", "rejected"]
    created_at: datetime
    candidate_count: int


class CampaignDirectory(BaseModel):
    items: list[CampaignSummary]
    next_before_created_at: datetime | None
    next_before_id: UUID | None
