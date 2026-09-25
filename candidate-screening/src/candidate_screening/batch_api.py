"""Recruiter reads used before a campaign is proposed or approved."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import recruiter_actor
from .campaigns import JobConfigResponse

router = APIRouter(prefix="/screening", tags=["screening batch preparation"])
Actor = Annotated[str, Depends(recruiter_actor)]


class ContactLookupRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=1000)


class ContactPreview(BaseModel):
    candidate_id: str
    email: str | None
    contactable: bool


@router.get("/jobs/{job_id}/latest-config", response_model=JobConfigResponse)
def latest_config(job_id: str, actor: Actor, request: Request):
    config = request.app.state.repo.latest_job_config(job_id)
    if config is None:
        raise HTTPException(status_code=404, detail="screening configuration not found")
    return config


@router.post("/contacts/lookup", response_model=list[ContactPreview])
def lookup_contacts(details: ContactLookupRequest, actor: Actor, request: Request):
    return request.app.state.repo.lookup_contacts(details.candidate_ids)
