from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.errors import UniqueViolation

from .auth import recruiter_actor
from .campaigns import (
    ApproveCampaignRequest,
    CampaignResponse,
    ContactRequest,
    ContactResponse,
    CreateCampaignRequest,
    CreateJobConfigRequest,
    EditCampaignRequest,
    JobConfigResponse,
)
from .pipeline import ScreeningPipeline
from .selection import SelectionRequest, SelectionResponse

router = APIRouter(prefix="/screening", tags=["screening proposals"])
Actor = Annotated[str, Depends(recruiter_actor)]


def pipeline(request: Request) -> ScreeningPipeline:
    return ScreeningPipeline(request.app.state.repo, request.app.state.settings.max_campaign_size)


@router.put("/candidates/{candidate_id}/contact", response_model=ContactResponse)
def set_contact(candidate_id: str, details: ContactRequest, actor: Actor, request: Request):
    result = request.app.state.repo.upsert_contact(
        candidate_id,
        details.email,
        details.source,
        details.source_reference,
        details.contactable,
        actor,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="active candidate not found")
    return result


@router.post("/jobs/{job_id}/configs", response_model=JobConfigResponse, status_code=201)
def create_config(job_id: str, details: CreateJobConfigRequest, actor: Actor, request: Request):
    try:
        result = request.app.state.repo.create_job_config(
            job_id, details.job_profile_version_id, details.questions, actor
        )
    except UniqueViolation as error:
        raise HTTPException(status_code=409, detail="configuration version exists") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=409, detail="approved job profile not found")
    return result


@router.get("/jobs/{job_id}/configs/{version}", response_model=JobConfigResponse)
def get_config(job_id: str, version: int, actor: Actor, request: Request):
    result = request.app.state.repo.get_job_config_version(job_id, version)
    if result is None:
        raise HTTPException(status_code=404, detail="configuration not found")
    return result


@router.post("/selections", response_model=SelectionResponse)
def select_batch(details: SelectionRequest, actor: Actor, request: Request):
    try:
        return pipeline(request).preview(details)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/campaigns", response_model=CampaignResponse, status_code=201)
def propose_campaign(details: CreateCampaignRequest, actor: Actor, request: Request):
    try:
        return pipeline(request).propose(details)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/campaigns/{campaign_id}", response_model=CampaignResponse)
def get_campaign(campaign_id: UUID, actor: Actor, request: Request):
    result = request.app.state.repo.get_campaign(campaign_id)
    if result is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return result


@router.patch("/campaigns/{campaign_id}", response_model=CampaignResponse)
def edit_campaign(campaign_id: UUID, details: EditCampaignRequest, actor: Actor, request: Request):
    try:
        return pipeline(request).edit(campaign_id, details)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/campaigns/{campaign_id}/reject", response_model=CampaignResponse)
def reject_campaign(campaign_id: UUID, expected_revision: int, actor: Actor, request: Request):
    result = request.app.state.repo.reject_campaign(campaign_id, expected_revision)
    if result is None:
        raise HTTPException(status_code=409, detail="campaign is no longer rejectable")
    return result


@router.post("/campaigns/{campaign_id}/approve", response_model=CampaignResponse)
def approve_campaign(
    campaign_id: UUID, details: ApproveCampaignRequest, actor: Actor, request: Request
):
    try:
        result = request.app.state.repo.approve_campaign(
            campaign_id,
            details.expected_revision,
            actor,
            request.app.state.settings.public_base_url,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return result
