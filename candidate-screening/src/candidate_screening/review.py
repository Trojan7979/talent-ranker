import base64
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .summary import Outcome

SortBy = Literal["outcome", "completed_at"]


class OutcomeCounts(BaseModel):
    proceed_to_interview: int = 0
    needs_recruiter_review: int = 0
    do_not_proceed: int = 0


class CompletedScreening(BaseModel):
    id: UUID
    invite_id: UUID
    campaign_id: UUID
    candidate_id: str
    outcome: Outcome
    confirmed: list[str]
    missing: list[str]
    needs_verification: list[str]
    reason_codes: list[str]
    policy_version: str
    config_version: int
    completed_at: datetime


class ReviewPage(BaseModel):
    campaign_id: UUID
    counts: OutcomeCounts
    items: list[CompletedScreening]
    next_cursor: str | None = None


class InviteActivity(BaseModel):
    invite_id: UUID
    candidate_id: str
    recipient_email: str
    delivery_status: Literal["pending", "processing", "sent", "failed", "unknown", "cancelled"]
    status: Literal["sent", "opened", "started", "completed", "expired", "declined"] | None
    sent_at: datetime | None
    opened_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime


class ActivityPage(BaseModel):
    campaign_id: UUID
    items: list[InviteActivity]
    next_cursor: str | None


class ReviewQuery(BaseModel):
    outcome: Outcome | None = None
    sort_by: SortBy = "outcome"
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None


def encode_cursor(item: dict, sort_by: SortBy) -> str:
    values = (
        [item["priority"], item["completed_at"].isoformat(), str(item["id"])]
        if sort_by == "outcome"
        else [item["completed_at"].isoformat(), str(item["id"])]
    )
    return base64.urlsafe_b64encode(json.dumps(values).encode()).decode().rstrip("=")


def decode_cursor(value: str, sort_by: SortBy) -> tuple:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        values = json.loads(raw)
        expected = 3 if sort_by == "outcome" else 2
        if not isinstance(values, list) or len(values) != expected:
            raise ValueError("wrong cursor shape")
        if sort_by == "outcome":
            priority, when, item_id = values
            if type(priority) is not int or priority not in (0, 1, 2):
                raise ValueError("invalid priority")
        else:
            when, item_id = values
        parsed = (datetime.fromisoformat(when), UUID(item_id))
        return (priority, *parsed) if sort_by == "outcome" else parsed
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid review cursor") from error
