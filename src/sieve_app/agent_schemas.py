from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CreateAgentSession(BaseModel):
    job_id: str | None = Field(default=None, min_length=1, max_length=200)
    ranking_run_id: UUID | None = None
    use_saved_run: bool = True


class AgentMessage(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class AgentSessionSummary(BaseModel):
    id: UUID
    job_id: str | None
    setup_stage: Literal["awaiting_jd", "awaiting_jd_approval", "awaiting_criteria_approval", "ranking", "ranked"]
    ranking_run_id: UUID | None
    created_at: datetime
    updated_at: datetime


class AgentSession(BaseModel):
    id: UUID
    job_id: str | None
    ranking_run_id: UUID | None
    setup_stage: Literal["awaiting_jd", "awaiting_jd_approval", "awaiting_criteria_approval", "ranking", "ranked"]
    ranking_status: Literal["pending", "running", "completed", "failed"] | None = None
    campaign_id: UUID | None
    question_draft: dict | None = None
    question_top_n: int | None = None
    question_draft_revision: int = 0
    question_config_id: UUID | None = None
    created_at: datetime
    messages: list[AgentMessage] = Field(default_factory=list)
    campaign: dict | None = None


class SendAgentMessage(BaseModel):
    content: str = Field(min_length=1, max_length=18000)


class AgentReply(BaseModel):
    session: AgentSession
    answer: str
    campaign: dict | None = None


class ApproveAgentCampaign(BaseModel):
    expected_revision: int = Field(ge=1)


class ApproveAgentQuestions(BaseModel):
    expected_revision: int = Field(ge=1)


class CampaignAction(BaseModel):
    campaign: dict
    delivery_status: Literal["queued"] = "queued"


class DispatchAction(BaseModel):
    campaign_id: UUID
    status: Literal["scheduled"] = "scheduled"
