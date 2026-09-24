from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .lifecycle import InviteStatus
from .questions import JobQuestions, ScreeningAnswers
from .summary import ScreeningSummary


class CandidateRequirement(BaseModel):
    id: str
    text: str


class CandidateQuestions(BaseModel):
    must_haves: list[CandidateRequirement]
    require_interest: bool
    require_availability: bool
    require_notice_period: bool
    require_salary: bool

    @classmethod
    def from_config(cls, config: JobQuestions) -> "CandidateQuestions":
        return cls(
            must_haves=[
                CandidateRequirement(id=item.id, text=item.text) for item in config.must_haves
            ],
            require_interest=config.require_interest,
            require_availability=config.require_availability,
            require_notice_period=config.require_notice_period,
            require_salary=config.require_salary,
        )


class InviteView(BaseModel):
    id: UUID
    campaign_id: UUID
    job_id: str
    status: InviteStatus | None
    expires_at: datetime
    opened_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    questions: CandidateQuestions


class SaveAnswersRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    answers: ScreeningAnswers


class DraftResponse(BaseModel):
    revision: int
    saved_at: datetime


class CompletionResponse(ScreeningSummary):
    id: UUID
    invite_id: UUID
    config_version: int
    generated_at: datetime
