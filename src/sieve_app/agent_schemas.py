from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CreateAgentSession(BaseModel):
    job_id: str = Field(min_length=1, max_length=200)
    ranking_run_id: UUID | None = None


class AgentMessage(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class AgentSession(BaseModel):
    id: UUID
    job_id: str
    ranking_run_id: UUID | None
    campaign_id: UUID | None
    created_at: datetime
    messages: list[AgentMessage] = Field(default_factory=list)
    campaign: dict | None = None


class SendAgentMessage(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class AgentReply(BaseModel):
    session: AgentSession
    answer: str
    campaign: dict | None = None


class ApproveAgentCampaign(BaseModel):
    expected_revision: int = Field(ge=1)


class CampaignAction(BaseModel):
    campaign: dict
    delivery_status: Literal["queued"] = "queued"
