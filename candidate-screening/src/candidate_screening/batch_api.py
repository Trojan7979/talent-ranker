"""Recruiter reads used before a campaign is proposed or approved."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from .auth import recruiter_actor
from .campaigns import JobConfigResponse

router = APIRouter(prefix="/screening", tags=["screening batch preparation"])
Actor = Annotated[str, Depends(recruiter_actor)]


class ContactLookupRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=1000)


class ContactPreview(BaseModel):
    candidate_id: str
    display_name: str | None = None
    name_source: str | None = None
    email: str | None
    contactable: bool


class CandidateNameRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=80)

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2 or any(ord(char) < 32 for char in value) or not any(char.isalpha() for char in value):
            raise ValueError("enter a candidate name")
        return value


class CandidateNameResponse(BaseModel):
    candidate_id: str
    display_name: str


@router.put("/candidates/{candidate_id}/name", response_model=CandidateNameResponse)
def set_candidate_name(candidate_id: str, details: CandidateNameRequest, actor: Actor, request: Request):
    result = request.app.state.repo.set_candidate_name(candidate_id, details.display_name)
    if result is None:
        raise HTTPException(status_code=404, detail="active candidate not found")
    return result


@router.get("/jobs/{job_id}/latest-config", response_model=JobConfigResponse)
def latest_config(job_id: str, actor: Actor, request: Request):
    config = request.app.state.repo.latest_job_config(job_id)
    if config is None:
        raise HTTPException(status_code=404, detail="screening configuration not found")
    return config


@router.post("/contacts/lookup", response_model=list[ContactPreview])
def lookup_contacts(details: ContactLookupRequest, actor: Actor, request: Request):
    return request.app.state.repo.lookup_contacts(details.candidate_ids)
