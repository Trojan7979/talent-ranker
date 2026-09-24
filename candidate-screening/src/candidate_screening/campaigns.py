from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

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
    message_template: str = Field(min_length=1, max_length=20000)
    expiry_hours: int = Field(default=48, ge=1, le=720)


class EditCampaignRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    final_candidate_ids: list[str] = Field(min_length=1, max_length=1000)
    message_template: str = Field(min_length=1, max_length=20000)


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
